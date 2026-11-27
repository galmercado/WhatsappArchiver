# Hardening guide and security posture

This archive holds other people's private conversations as well as yours. Treat the server as a vault, not a website.

## What the design guarantees (and the test that proves it)

| Property | Mechanism | Evidence |
|---|---|---|
| Backup key never reaches the server | decryption only in `extract_and_ingest.py`; secrets never on argv | `tests/test_cli.py`, `tests/test_pipeline.py` |
| Data encrypted at rest | SQLCipher (AES-256) + per-file AES-CTR media blobs with opaque names; keys derived from your passphrase with Argon2id | `test_normalize_archive.py`, `test_media_vault.py` |
| Nothing readable while locked | keys live only in server RAM; *Lock vault* zeroes them, closes the media vault, ends all sessions; idle auto-lock | `tests/server/test_vault.py` |
| Login can't be brute-forced | per-IP and global exponential backoff, TOTP replay protection, generic errors | `test_auth_password.py`, `test_auth_google.py` |
| No unauthenticated data path | auth dependency on every data route; route-walk test | `tests/server/test_security.py` |
| No stored XSS from hostile messages | text rendered as React text nodes only; lint + source scan ban HTML sinks; strict CSP | `richtext.test.tsx`, `MessageBubble.test.tsx`, e2e |
| No path traversal / injection | media paths come from the DB, never the client; parameterised SQL; FTS input tokenised and quoted | `test_media.py`, `test_api.py` |
| No PII in logs | scrubbing filter + route-template-only access log; Caddy logs drop URIs, headers and IPs | `test_security.py`, `test_deploy_files.py` |
| Deployment can't silently weaken | compose/Caddy/CI regression tests (mutation-checked) | `tests/test_deploy_files.py` |

## Checklist before exposing it

**Host**
- [ ] Full-disk encryption (LUKS) on the volume that holds `archive/`; the passphrase prompt on boot is a feature.
- [ ] Swap disabled or encrypted (`swapoff -a`, or `cryptswap`): unlocked keys must not reach unencrypted disk.
- [ ] Firewall allows only 80/443 (Caddy) or nothing inbound (Tunnel/Tailscale): `ufw default deny incoming`.
- [ ] SSH: keys only, no root login, `fail2ban` or equivalent; unattended security updates on.
- [ ] `chmod -R go-rwx archive secrets .env`; `secrets/` is git-ignored and `.dockerignore`d.

**Accounts**
- [ ] Password mode: ≥ 14-character unique password, TOTP in an authenticator app, recovery codes stored offline.
- [ ] Google mode: Google account protected with a passkey/2-step verification; consent screen in *Testing* with only you as test user.
- [ ] Vault passphrase ≥ 20 characters and different from the login password (it is the actual key to the data).

**Containers**
- [ ] Pin base images by digest in the `Dockerfile`/compose (`image: caddy@sha256:…`); let Dependabot propose bumps.
- [ ] Review the Trivy output in CI; rebuild images at least monthly for OS patches.
- [ ] Do not mount the Docker socket anywhere; keep `app` on the `internal` network unless using Google mode.

**GitHub**
- [ ] Branch protection on `main`: require the `test-and-security` checks; enable secret scanning and push protection.
- [ ] Pin third-party actions to commit SHAs (Dependabot keeps them current) once you are happy with the versions.

## Known limits (read these)

1. **Unverified against real WhatsApp files.** The crypt14/15 reader follows published reverse-engineering notes and is
   tested against my own fixtures. Validate with one real backup before relying on it; authentication tags make a wrong
   guess fail loudly rather than corrupt data.
2. **While the vault is unlocked, root on the server can read keys from memory.** Lock it when you are not using it.
3. **Media blobs are encrypted but not individually authenticated** (CTR is needed for byte-range seeking). Someone with
   write access to the volume could corrupt a file, not read it. The database itself is authenticated.
4. **Single process only.** Sessions, rate limits and the vault are in memory; restarts log everyone out and lock the vault.
5. **Google ID token signatures are not verified** (allowed by OIDC when the token comes straight from Google's token
   endpoint over TLS with your client secret). Issuer, audience, expiry, nonce, verified email and your pinned identity are checked.
6. **Wiping temporary plaintext during ingest is best-effort** on SSDs and copy-on-write filesystems; run ingest on an encrypted disk.
7. **Container images could not be built in the environment where this was written** (no Docker daemon). Compose files and
   the workflow are validated (`docker compose config`, `actionlint`) and covered by tests, but run
   `docker compose --profile dev up --build` once and let CI go green before trusting the images.
8. **Dev-only npm advisories** exist for Vite/Vitest (not shipped in the app); CI gates on production dependencies and reports the rest.

## If something looks wrong

1. *Lock vault* in the UI (or `docker compose stop app`). This makes the data unreadable immediately.
2. Rotate: regenerate `secrets/*`, change the Google OAuth client secret, revoke the Cloudflare/Tailscale key.
3. Check `docker compose logs` (no PII) and your host's auth logs; the archive file itself is useless without the passphrase.
4. If the vault passphrase may be exposed, re-ingest into a new archive with a new passphrase and destroy the old one.
