"""Authentication, vault unlock/lock. Only the configured auth mode's routes are mounted."""

from __future__ import annotations

import hmac
import secrets
from typing import Annotated

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from . import oidc
from .context import AppContext, CsrfSession, Ctx, CurrentSession, optional_session
from .models import LoginIn, OkOut, StatusOut, UnlockIn
from .sessions import Session
from .vault import WrongPassphraseError

_hasher = PasswordHasher()
TOTP_STEP = 30


def _set_session_cookie(ctx: AppContext, response: Response, sid: str) -> None:
    response.set_cookie(
        ctx.cookie_name, sid, httponly=True, secure=ctx.settings.cookie_secure,
        samesite="strict", path="/",
    )  # fmt: skip


def _clear_session_cookie(ctx: AppContext, response: Response) -> None:
    response.delete_cookie(
        ctx.cookie_name,
        path="/",
        httponly=True,
        secure=ctx.settings.cookie_secure,
        samesite="strict",
    )


def common_router() -> APIRouter:
    r = APIRouter()

    @r.get("/auth/status", response_model=StatusOut)
    def status(
        ctx: Ctx, session: Annotated[Session | None, Depends(optional_session)]
    ) -> StatusOut:
        return StatusOut(
            auth_mode=ctx.settings.auth_mode,
            authenticated=session is not None,
            vault_unlocked=session is not None and ctx.vault.unlocked,
            csrf_token=session.csrf if session else None,
        )

    @r.post("/auth/logout", response_model=OkOut)
    def logout(request: Request, response: Response, ctx: Ctx, _s: CsrfSession) -> OkOut:
        ctx.sessions.destroy(request.cookies.get(ctx.cookie_name))
        _clear_session_cookie(ctx, response)
        return OkOut()

    @r.post("/vault/unlock", response_model=OkOut)
    def unlock(body: UnlockIn, request: Request, ctx: Ctx, _s: CsrfSession) -> OkOut:
        ip = ctx.client_ip(request)
        ctx.check_limits((ctx.unlock_ip, ip), (ctx.unlock_global, "unlock"))
        try:
            ctx.vault.unlock(bytearray(body.passphrase.encode("utf-8")))
        except WrongPassphraseError:
            ctx.unlock_ip.fail(ip)
            ctx.unlock_global.fail("unlock")
            raise HTTPException(401, "unlock failed") from None
        ctx.unlock_ip.success(ip)
        ctx.unlock_global.success("unlock")
        return OkOut()

    @r.post("/vault/lock", response_model=OkOut)
    def lock(response: Response, ctx: Ctx, _s: CsrfSession) -> OkOut:
        """Purge keys from memory and end every session."""
        ctx.lock_everything()
        _clear_session_cookie(ctx, response)
        return OkOut()

    return r


def password_router() -> APIRouter:
    r = APIRouter()

    def verify_password(ctx: AppContext, password: str) -> bool:
        try:
            return _hasher.verify(ctx.settings.password_hash or "", password)
        except (VerificationError, InvalidHashError):
            return False

    def verify_totp(ctx: AppContext, code: str) -> int | None:
        """Return the matched time-step counter (must be newer than the last used)."""
        secret = ctx.settings.totp_secret
        totp = pyotp.TOTP(secret.get_secret_value() if secret else "")
        now_ctr = int(ctx.wall() // TOTP_STEP)
        hit: int | None = None
        for ctr in (now_ctr - 1, now_ctr, now_ctr + 1):  # always evaluate all three
            if hmac.compare_digest(totp.at(ctr * TOTP_STEP), code) and ctr > ctx.last_totp_counter:
                hit = ctr
        return hit

    @r.post("/auth/login", response_model=OkOut)
    def login(body: LoginIn, request: Request, response: Response, ctx: Ctx) -> OkOut:
        ip = ctx.client_ip(request)
        ctx.check_limits((ctx.ip_limiter, ip), (ctx.global_limiter, "login"))
        pw_ok = verify_password(ctx, body.password)  # both factors always evaluated
        ctr = verify_totp(ctx, body.totp)
        if not (pw_ok and ctr is not None):
            ctx.ip_limiter.fail(ip)
            ctx.global_limiter.fail("login")
            raise HTTPException(401, "invalid credentials")
        with ctx._totp_lock:
            if ctr <= ctx.last_totp_counter:
                raise HTTPException(401, "invalid credentials")
            ctx.last_totp_counter = ctr
        ctx.ip_limiter.success(ip)
        ctx.global_limiter.success("login")
        sid, session = ctx.sessions.create("password_totp")  # fresh id: no session fixation
        _set_session_cookie(ctx, response, sid)
        return OkOut(csrf_token=session.csrf)

    return r


def google_router() -> APIRouter:
    r = APIRouter()
    bind_cookie = "wa_oauth"

    @r.get("/auth/google/start")
    def start(request: Request, ctx: Ctx) -> RedirectResponse:
        ip = ctx.client_ip(request)
        ctx.check_limits((ctx.ip_limiter, ip), (ctx.global_limiter, "login"))
        state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        verifier, binding = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        try:
            ctx.pending.put(
                state, oidc.Pending(verifier, nonce, binding, ctx.clock() + oidc.PENDING_TTL_S)
            )
        except oidc.OIDCError:
            raise HTTPException(429, "too many attempts", headers={"Retry-After": "60"}) from None
        resp = RedirectResponse(
            oidc.authorize_url(ctx.settings, state=state, nonce=nonce, verifier=verifier),
            status_code=302,
        )
        # Lax (not Strict): Google redirects back via a cross-site top-level navigation.
        resp.set_cookie(
            bind_cookie, binding, httponly=True, secure=ctx.settings.cookie_secure,
            samesite="lax", path="/auth/google", max_age=oidc.PENDING_TTL_S,
        )  # fmt: skip
        return resp

    @r.get("/auth/google/callback")
    def callback(
        request: Request,
        ctx: Ctx,
        code: str | None = Query(default=None, max_length=2048),
        state: str | None = Query(default=None, max_length=256),
        error: str | None = Query(default=None, max_length=256),
    ) -> RedirectResponse:
        ip = ctx.client_ip(request)
        ctx.check_limits((ctx.ip_limiter, ip), (ctx.global_limiter, "login"))
        fail = RedirectResponse("/?login=failed", status_code=303)
        fail.delete_cookie(bind_cookie, path="/auth/google")

        def reject() -> RedirectResponse:
            ctx.ip_limiter.fail(ip)
            ctx.global_limiter.fail("login")
            return fail

        if error or not code or not state or ctx.oidc is None:
            return reject()
        pend = ctx.pending.pop(state)  # one-time use
        cookie = request.cookies.get(bind_cookie, "")
        if pend is None or not cookie or not hmac.compare_digest(cookie, pend.binding):
            return reject()
        try:
            claims = ctx.oidc.exchange(
                code=code,
                code_verifier=pend.verifier,
                redirect_uri=ctx.settings.google_redirect_uri,
            )
            oidc.validate_claims(claims, ctx.settings, nonce=pend.nonce, now=ctx.wall())
        except oidc.OIDCError:
            return reject()
        ctx.ip_limiter.success(ip)
        ctx.global_limiter.success("login")
        sid, _ = ctx.sessions.create("google")
        ok = RedirectResponse("/", status_code=303)
        _set_session_cookie(ctx, ok, sid)
        ok.delete_cookie(bind_cookie, path="/auth/google")
        return ok

    return r


__all__ = ["CurrentSession", "common_router", "google_router", "password_router"]
