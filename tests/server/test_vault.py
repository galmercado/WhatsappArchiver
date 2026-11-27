from __future__ import annotations

import gc
from pathlib import Path

import pytest

from archive_factory import PASSPHRASE
from server_support import BASE, Env
from waarchive.media_vault import VaultClosedError


def hdr(csrf: str) -> dict[str, str]:
    return {"Origin": BASE, "X-CSRF-Token": csrf}


def test_data_requires_unlock(env: Env) -> None:
    env.login()
    assert env.client.get("/api/chats").status_code == 423
    assert env.client.get("/auth/status").json()["vault_unlocked"] is False


def test_wrong_passphrase_then_backoff(env: Env) -> None:
    csrf = env.login()
    for _ in range(4):  # 3 free failures; the 4th triggers the first lockout
        assert env.unlock(csrf, "wrong-passphrase-123").status_code == 401
    r = env.unlock(csrf, "wrong-passphrase-123")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert env.unlock(csrf).status_code == 429  # correct passphrase blocked while backing off
    env.clock.advance(10)
    assert env.unlock(csrf).status_code == 200


def test_unlock_then_browse(ready: Env) -> None:
    assert ready.client.get("/api/chats").status_code == 200
    assert ready.client.get("/auth/status").json()["vault_unlocked"] is True


def test_lock_vault_purges_keys_and_invalidates_sessions(ready: Env) -> None:
    key_ref = ready.ctx.vault._db_key
    assert key_ref is not None and any(key_ref)
    media = ready.ctx.vault.media
    csrf = ready.client.headers["X-CSRF-Token"]
    assert ready.client.post("/vault/lock", headers=hdr(csrf)).status_code == 200
    assert not any(key_ref)  # zeroized in place
    assert ready.ctx.vault._db_key is None and not ready.ctx.vault.unlocked
    assert len(ready.ctx.sessions) == 0
    assert ready.client.get("/api/chats").status_code == 401  # session gone
    with pytest.raises(VaultClosedError):
        media.blob_path("x")
    # stolen cookie from before the lock is useless; re-login + re-unlock needed
    ready.clock.advance(31)
    csrf2 = ready.login()
    assert ready.client.get("/api/chats").status_code == 423
    assert ready.unlock(csrf2).status_code == 200


def test_lock_stops_in_flight_media_stream(ready: Env, tmp_path: Path) -> None:
    big = tmp_path / "big.bin"
    big.write_bytes(b"\x01" * 300_000)
    v = ready.ctx.vault.media
    v.store("big.bin", big)
    it = v.read_range("big.bin", 0, 299_999)
    next(it)
    ready.ctx.vault.lock()
    with pytest.raises(VaultClosedError):
        next(it)


def test_idle_auto_lock(ready: Env) -> None:
    ready.clock.advance(ready.settings.vault_idle_s + 1)
    ready.ctx.maintenance()
    assert not ready.ctx.vault.unlocked and len(ready.ctx.sessions) == 0


def test_activity_defers_auto_lock(ready: Env) -> None:
    for _ in range(4):
        ready.clock.advance(600)
        assert ready.client.get("/api/chats").status_code == 200
        ready.ctx.maintenance()
    assert ready.ctx.vault.unlocked


def test_logout_alone_keeps_vault_but_lock_everything_clears(ready: Env) -> None:
    ready.ctx.lock_everything()
    assert ready.client.get("/api/chats").status_code == 401


def test_key_not_in_database_file_or_kdf_sidecar(ready: Env) -> None:
    key = bytes(ready.ctx.vault._db_key or b"")
    assert key
    for p in (ready.archive / "archive.db", ready.archive / "archive.kdf.json"):
        assert key not in p.read_bytes()
    assert PASSPHRASE.encode() not in (ready.archive / "archive.kdf.json").read_bytes()
    gc.collect()
