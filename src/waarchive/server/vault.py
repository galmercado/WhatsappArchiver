"""In-memory vault state: derives keys from the passphrase and holds them until locked."""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any

from ..ingest.archive import DatabaseProvider, DBConnection, WrongKeyError
from ..keys import KeyError_, derive_master, read_params, subkey
from ..media_vault import MediaVault
from ..secure_fs import zeroize
from .settings import Settings

QUERY_BUDGET_S = 3.0


class WrongPassphraseError(Exception):
    pass


class VaultLockedError(Exception):
    pass


class VaultState:
    def __init__(
        self, settings: Settings, provider: DatabaseProvider, clock: Callable[[], float]
    ) -> None:
        self._s, self._provider, self._clock = settings, provider, clock
        self._lock = threading.RLock()
        self._db_key: bytearray | None = None
        self._media: MediaVault | None = None
        self._last_activity = 0.0

    @property
    def unlocked(self) -> bool:
        return self._db_key is not None

    def unlock(self, passphrase: bytearray) -> None:
        d = self._s.archive_dir
        try:
            params = read_params(d / "archive.kdf.json")
            master = derive_master(passphrase, params)
        except KeyError_ as exc:
            raise WrongPassphraseError("unlock failed") from exc
        finally:
            zeroize(passphrase)
        try:
            db_key = bytearray(subkey(master, "db"))
            media = MediaVault(d / "media", subkey(master, "media"), subkey(master, "media-name"))
        finally:
            zeroize(master)
        try:
            self._provider.open(d / "archive.db", bytes(db_key), read_only=True).close()
        except WrongKeyError as exc:
            zeroize(db_key)
            raise WrongPassphraseError("unlock failed") from exc
        with self._lock:
            self._purge()
            self._db_key, self._media = db_key, media
            self._last_activity = self._clock()

    def _purge(self) -> None:
        zeroize(self._db_key)
        self._db_key = None
        if self._media is not None:
            self._media.close()
        self._media = None

    def lock(self) -> None:
        with self._lock:
            self._purge()

    def touch(self) -> None:
        self._last_activity = self._clock()

    def idle_expired(self) -> bool:
        return self.unlocked and self._clock() - self._last_activity > self._s.vault_idle_s

    @property
    def media(self) -> MediaVault:
        m = self._media
        if m is None:
            raise VaultLockedError("vault is locked")
        return m

    @contextlib.contextmanager
    def db(self) -> Iterator[DBConnection]:
        with self._lock:
            if self._db_key is None:
                raise VaultLockedError("vault is locked")
            key = bytes(self._db_key)
        conn = self._provider.open(self._s.archive_dir / "archive.db", key, read_only=True)
        deadline = time.monotonic() + QUERY_BUDGET_S
        handler: Any = getattr(conn, "set_progress_handler", None)
        if handler:
            handler(lambda: 1 if time.monotonic() > deadline else 0, 20_000)
        try:
            yield conn
        finally:
            conn.close()
