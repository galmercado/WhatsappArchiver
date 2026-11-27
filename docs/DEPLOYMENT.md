# Deployment guide

Two ways to run it, each with two auth options (`password_totp` or `google`). Everything below uses the
same image; only compose profiles and env differ.

```
 Browser ──HTTPS──► Caddy :443 ──(internal network, no internet)──► app :8000 ──► /data (archive, read-only)
                    └ or Cloudflare Tunnel / Tailscale instead of Caddy
```

## 0. Produce the archive (on your own computer, offline from the server)

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
python extract_and_ingest.py --out ./archive      # prompts for the vault passphrase and (unrooted) your 64-digit key
```

`./archive` contains `archive.db`, `archive.kdf.json` and `media/`. **Your WhatsApp backup key never goes to the
server**; the server only ever receives the already-encrypted archive. Copy `archive/` to the host (scp/rsync over
SSH) and keep it `chmod -R go-rwx`.

## 1. Local debugging (bound to 127.0.0.1)

**Without Docker** (hot reload on both sides):

```bash
export WA_ENV=dev WA_ARCHIVE_DIR=./archive WA_BASE_URL=http://localhost:5173 WA_PORT=8000
# auth: see README ("Server"). Then:
python -m waarchive.server --reload --verbose     # API on 127.0.0.1:8000
cd web && npm install && npm run dev              # UI on http://localhost:5173 (proxies /api /auth /vault)
```

**With Docker** (single command, loopback-only, Python hot reload):

```bash
cp .env.example .env                              # choose COMPOSE_FILE + WA_AUTH_MODE
python -m waarchive.server.setup_auth             # password mode: copy the two values into secrets/ (below)
install -m 600 /dev/null secrets/password_hash && printf '%s' '<hash>'  > secrets/password_hash
install -m 600 /dev/null secrets/totp_secret    && printf '%s' '<secret>' > secrets/totp_secret
docker compose --profile dev up --build           # http://localhost:8000  (published on 127.0.0.1 only)
```

Logs are verbose but PII-scrubbed (route templates and status codes only; never queries, names, numbers or file names).

**Google OAuth on localhost:** Google Cloud Console → *APIs & Services → Credentials → Create OAuth client ID
(Web application)* → authorized redirect URI `http://localhost:8000/auth/google/callback` (use the port you publish).
Put the client id in `.env`, the secret in `secrets/google_client_secret`, your account in `WA_GOOGLE_ALLOWED_EMAIL`.

## 2. Production with automatic TLS (Caddy)

Prerequisites: a host with Docker, a DNS `A/AAAA` record for `WA_DOMAIN`, ports 80 and 443 reachable.

```bash
# .env
WA_DOMAIN=archive.example.com
ACME_EMAIL=you@example.com
COMPOSE_FILE=docker-compose.yml:docker-compose.password.yml     # or ...google.yml
WA_AUTH_MODE=password_totp                                       # or google
WA_ARCHIVE_PATH=/srv/wa-archive/archive

docker compose --profile prod up -d --build
docker compose --profile prod ps                                  # app should become "healthy"
```

The app container has **no published ports** and sits on an `internal` network with no route to the internet
(the Google override adds a separate `egress` network because it must reach Google). Only Caddy listens publicly.

First-run checks:

```bash
curl -sI https://$WA_DOMAIN/ | grep -iE 'strict-transport|content-security|x-content-type|cache-control'
curl -s -o /dev/null -w '%{http_code}\n' https://$WA_DOMAIN/api/chats     # expect 401
curl -s -o /dev/null -w '%{http_code}\n' https://$WA_DOMAIN/healthz        # expect 404 (internal only)
```

**Moving Google OAuth from localhost to your domain:** add a second authorized redirect URI
`https://archive.example.com/auth/google/callback` to the same OAuth client, keep the OAuth consent screen in
*Testing* with only your account as a test user (or publish as *Internal* for a Workspace domain). `WA_BASE_URL`
is derived from `WA_DOMAIN` by compose, so no other change is needed. Pinning `WA_GOOGLE_ALLOWED_SUB` is optional
extra hardening (email is already checked, and must be *verified*).

## 3. Private remote access without opening any port

Pick **one**; do not run Caddy at the same time.

**Cloudflare Tunnel** (works with a custom domain, including Google OAuth):
1. Zero Trust dashboard → Networks → Tunnels → create a tunnel, copy the token into `.env` as `CLOUDFLARE_TUNNEL_TOKEN`.
2. Public hostname `archive.example.com` → service `http://app:8000`. Set `WA_DOMAIN=archive.example.com`.
3. `docker compose --profile tunnel up -d --build`. Optionally add a Cloudflare Access policy as an extra gate in front.

**Tailscale** (nothing reachable from the public internet):
1. Create an *ephemeral, single-use* auth key; set `TS_AUTHKEY` and `TS_HOSTNAME` in `.env`.
2. Enable HTTPS certificates in the Tailscale admin console; set `WA_DOMAIN=<hostname>.<tailnet>.ts.net`.
3. `docker compose --profile tailscale up -d --build`; browse to `https://<hostname>.<tailnet>.ts.net`.
4. Use `password_totp` here. I have **not** verified that Google accepts `*.ts.net` redirect URIs; if you need Google
   sign-in, use the Cloudflare Tunnel (or Caddy) route with a domain you own.

## 4. Operating it

| Task | How |
|---|---|
| Update | `git pull && docker compose --profile prod up -d --build` (CI must be green first) |
| Lock now | UI menu → *Lock vault* (purges keys, ends every session); `docker compose stop app` also clears memory |
| New archive / rotate vault passphrase | re-run `extract_and_ingest.py` with a new passphrase into a new directory, swap `WA_ARCHIVE_PATH`, restart |
| Rotate login secrets | regenerate with `setup_auth`, replace the files in `secrets/`, `docker compose up -d` |
| Backups | back up `archive/` (already encrypted) to encrypted storage; **the passphrase is not recoverable** |
| Logs | `docker compose logs -f app caddy` (no PII by construction) |

## 5. Troubleshooting

* **`prod requires an https WA_BASE_URL` / `set WA_DOMAIN`** – `WA_DOMAIN` is unset or a placeholder; the app refuses to start.
* **Login loops back to the sign-in page after Google** – the redirect URI in Google Console must match `WA_BASE_URL` exactly (scheme, host, port).
* **`429 too many attempts`** – exponential backoff is working; wait the `Retry-After` seconds. Counters live in memory and reset on restart.
* **Run exactly one app process.** Sessions, rate limits and the unlocked vault live in process memory; do not scale `app` horizontally or add uvicorn workers.
