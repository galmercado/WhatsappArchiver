"""Server-side sessions. Only a SHA-256 of the session id is kept in memory."""

from __future__ import annotations

import hashlib
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Session:
    key: str
    csrf: str
    created: float
    last_seen: float
    method: str


def _h(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8", "replace")).hexdigest()


class SessionStore:
    def __init__(self, clock: Callable[[], float], idle_s: int, max_s: int) -> None:
        self._clock, self._idle, self._max = clock, idle_s, max_s
        self._s: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, method: str) -> tuple[str, Session]:
        sid = secrets.token_urlsafe(32)
        now = self._clock()
        sess = Session(_h(sid), secrets.token_urlsafe(32), now, now, method)
        with self._lock:
            self._s[sess.key] = sess
        return sid, sess

    def get(self, sid: str | None) -> Session | None:
        if not sid or len(sid) > 128:
            return None
        key = _h(sid)
        now = self._clock()
        with self._lock:
            s = self._s.get(key)
            if s is None:
                return None
            if now - s.last_seen > self._idle or now - s.created > self._max:
                del self._s[key]
                return None
            s.last_seen = now
            return s

    def destroy(self, sid: str | None) -> None:
        if sid:
            with self._lock:
                self._s.pop(_h(sid), None)

    def destroy_all(self) -> None:
        with self._lock:
            self._s.clear()

    def purge(self) -> None:
        now = self._clock()
        with self._lock:
            for k in [
                k
                for k, s in self._s.items()
                if now - s.last_seen > self._idle or now - s.created > self._max
            ]:
                del self._s[k]

    def __len__(self) -> int:
        return len(self._s)
