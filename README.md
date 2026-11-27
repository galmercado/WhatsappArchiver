# WhatsappArchiver

Self-hosted, zero-trust WhatsApp archive. **Status: Phase 2 (extraction/decryption CLI) complete.**
Phases 3–5 (FastAPI backend, React UI, deployment) follow.

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
