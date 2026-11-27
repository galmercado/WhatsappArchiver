# WhatsappArchiver

Self-hosted, zero-trust WhatsApp archive. **Status: Phase 2 (ingest CLI) and Phase 3 (hardened FastAPI backend) complete.**
Phases 4–5 (React UI, deployment/CI) follow.

## Ingest

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
python extract_and_ingest.py --out ./archive            # via ADB (rooted or unrooted flow)
python extract_and_ingest.py --bundle ./my_export --out ./archive   # offline, no phone
```

Secrets are never taken from argv: the archive passphrase comes from a hidden prompt or
`WA_ARCHIVE_PASSPHRASE`; the 64-digit backup key is prompted for (hidden). Output:
`archive.db` (SQLCipher + FTS5), `archive.kdf.json`, `media/` (AES-256-CTR blobs).

## Checks

```bash
pytest --cov=waarchive
ruff check . && ruff format --check .
mypy
bandit -q -r src extract_and_ingest.py -c pyproject.toml
pip-audit --skip-editable
```

Fixture generator: `python tests/fixtures/generate_mock_whatsapp.py OUTDIR`.

## Server (local debug, 127.0.0.1 only)

Auth is chosen by `WA_AUTH_MODE`; only that mode's routes are mounted. Either way, unlocking
the archive additionally requires the vault passphrase (Google/TOTP prove *who you are*, they
cannot decrypt anything).

```bash
export WA_ENV=dev WA_ARCHIVE_DIR=./archive WA_BASE_URL=http://localhost:8000
# --- option A: Argon2id password + TOTP
python -m waarchive.server.setup_auth          # prints WA_PASSWORD_HASH / WA_TOTP_SECRET + otpauth URI
export WA_AUTH_MODE=password_totp WA_PASSWORD_HASH='...' WA_TOTP_SECRET='...'
# --- option B: Google OAuth (OpenID Connect + PKCE), pinned to one account
export WA_AUTH_MODE=google WA_GOOGLE_CLIENT_ID=... WA_GOOGLE_CLIENT_SECRET=... \
       WA_GOOGLE_ALLOWED_EMAIL=you@gmail.com   # optionally WA_GOOGLE_ALLOWED_SUB=<your Google sub>
python -m waarchive.server --reload            # http://localhost:8000
```

Google setup (localhost): Google Cloud Console > APIs & Services > Credentials > OAuth client ID
(Web application) > authorized redirect URI `http://localhost:8000/auth/google/callback`.
Use `localhost`, not a LAN IP.

API (all require session + unlocked vault; GET unless noted): `/api/chats`, `/api/chats/{id}`,
`/api/chats/{id}/messages?before|after|around`, `/api/search?q=&chat_id=`, `/api/media/{message_id}`
(HTTP Range). Session endpoints: `/auth/status`, `/auth/login` | `/auth/google/start`,
`/auth/logout`, `POST /vault/unlock`, `POST /vault/lock` (purges keys, ends every session).
