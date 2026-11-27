"""Application context + request dependencies (session, CSRF, vault state, client IP)."""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from ..ingest.archive import DatabaseProvider
from .oidc import OIDCClient, PendingStore
from .ratelimit import Backoff
from .sessions import Session, SessionStore
from .settings import Settings
from .vault import VaultLockedError, VaultState


@dataclass
class AppContext:
    settings: Settings
    provider: DatabaseProvider
    oidc: OIDCClient | None = None
    clock: Callable[[], float] = time.monotonic
    wall: Callable[[], float] = time.time
    sessions: SessionStore = field(init=False)
    vault: VaultState = field(init=False)
    ip_limiter: Backoff = field(init=False)
    global_limiter: Backoff = field(init=False)
    unlock_ip: Backoff = field(init=False)
    unlock_global: Backoff = field(init=False)
    pending: PendingStore = field(init=False)
    last_totp_counter: int = 0
    _totp_lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        s, c = self.settings, self.clock
        self.sessions = SessionStore(c, s.session_idle_s, s.session_max_s)
        self.vault = VaultState(s, self.provider, c)
        self.ip_limiter = Backoff(
            c, free=s.ip_free_attempts, base=s.backoff_base_s, maximum=s.backoff_max_s
        )
        self.global_limiter = Backoff(
            c, free=s.global_free_attempts, base=s.backoff_base_s, maximum=300.0
        )
        self.unlock_ip = Backoff(
            c, free=s.ip_free_attempts, base=s.backoff_base_s, maximum=s.backoff_max_s
        )
        self.unlock_global = Backoff(
            c, free=s.global_free_attempts, base=s.backoff_base_s, maximum=300.0
        )
        self.pending = PendingStore(c)

    @property
    def cookie_name(self) -> str:
        return "__Host-wa_session" if self.settings.cookie_secure else "wa_session"

    def lock_everything(self) -> None:
        self.vault.lock()
        self.sessions.destroy_all()

    def maintenance(self) -> None:
        """Periodic: drop expired sessions; auto-lock an idle vault (and end all sessions)."""
        self.sessions.purge()
        if self.vault.idle_expired():
            self.lock_everything()

    def client_ip(self, request: Request) -> str:
        if self.settings.trust_proxy:
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                return xff.split(",")[-1].strip()[:64]
        return request.client.host if request.client else "unknown"

    def check_limits(self, *limiters: tuple[Backoff, str]) -> None:
        wait = max((lim.retry_after(key) for lim, key in limiters), default=0)
        if wait:
            raise HTTPException(429, "too many attempts", headers={"Retry-After": str(wait)})


def get_ctx(request: Request) -> AppContext:
    ctx: AppContext = request.app.state.ctx
    return ctx


Ctx = Annotated[AppContext, Depends(get_ctx)]


def optional_session(request: Request, ctx: Ctx) -> Session | None:
    return ctx.sessions.get(request.cookies.get(ctx.cookie_name))


def require_session(request: Request, ctx: Ctx) -> Session:
    s = ctx.sessions.get(request.cookies.get(ctx.cookie_name))
    if s is None:
        raise HTTPException(401, "authentication required")
    return s


CurrentSession = Annotated[Session, Depends(require_session)]


def require_csrf(request: Request, session: CurrentSession) -> Session:
    sent = request.headers.get("x-csrf-token", "")
    if not sent or not hmac.compare_digest(sent.encode(), session.csrf.encode()):
        raise HTTPException(403, "invalid CSRF token")
    return session


CsrfSession = Annotated[Session, Depends(require_csrf)]


def require_unlocked(ctx: Ctx, _session: CurrentSession) -> None:
    if not ctx.vault.unlocked:
        raise HTTPException(423, "vault is locked")
    ctx.vault.touch()


def new_csrf() -> str:
    return secrets.token_urlsafe(32)


__all__ = [
    "AppContext",
    "CsrfSession",
    "Ctx",
    "CurrentSession",
    "VaultLockedError",
    "get_ctx",
    "optional_session",
    "require_csrf",
    "require_session",
    "require_unlocked",
]  # fmt: skip
