"""FastAPI application factory with defence-in-depth middleware."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..ingest.archive import DatabaseProvider, SQLCipherProvider
from ..logsafe import RedactingFilter
from .context import AppContext
from .oidc import GoogleOIDC, OIDCClient
from .routes_api import api_router
from .routes_auth import common_router, google_router, password_router
from .settings import Settings

log = logging.getLogger("waarchive.server")
MAX_BODY = 64 * 1024
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


IMMUTABLE = "public, max-age=31536000, immutable"


def _security_headers(resp: Response, settings: Settings, path: str = "") -> None:
    h = resp.headers
    h.setdefault("Content-Security-Policy", CSP)
    h["X-Content-Type-Options"] = "nosniff"
    if path.startswith("/assets/") and resp.status_code == 200:
        h["Cache-Control"] = IMMUTABLE  # content-hashed build output only
    else:
        h["Cache-Control"] = "no-store"
        h["Pragma"] = "no-cache"
    h["Referrer-Policy"] = "no-referrer"
    h["X-Frame-Options"] = "DENY"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["Cross-Origin-Resource-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    if settings.env == "prod":
        h["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    if "server" in h:
        del h["server"]


def create_app(
    settings: Settings,
    *,
    oidc_client: OIDCClient | None = None,
    provider: DatabaseProvider | None = None,
    clock: Callable[[], float] = time.monotonic,
    wall: Callable[[], float] = time.time,
) -> FastAPI:
    if settings.auth_mode == "google" and oidc_client is None:
        oidc_client = GoogleOIDC(settings)
    ctx = AppContext(settings, provider or SQLCipherProvider(), oidc_client, clock=clock, wall=wall)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async def loop() -> None:
            while True:
                await asyncio.sleep(15)
                ctx.maintenance()

        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            task.cancel()
            ctx.lock_everything()

    app = FastAPI(
        title="WhatsApp Archive", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.ctx = ctx
    app.include_router(common_router())
    app.include_router(
        password_router() if settings.auth_mode == "password_totp" else google_router()
    )
    app.include_router(api_router())

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    if settings.static_dir is not None:
        _mount_spa(app, settings.static_dir.resolve())

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, _e: RequestValidationError) -> JSONResponse:
        # Deliberately omit the default `input` echo: bodies contain passwords/passphrases.
        return JSONResponse({"detail": "invalid request"}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_r: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"detail": str(exc.detail)}, status_code=exc.status_code, headers=exc.headers
        )

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        t0 = time.monotonic()
        resp: Response
        try:
            if request.method in UNSAFE:
                if request.headers.get("origin") != settings.origin:
                    resp = JSONResponse({"detail": "bad origin"}, status_code=403)
                elif int(request.headers.get("content-length") or 0) > MAX_BODY:
                    resp = JSONResponse({"detail": "payload too large"}, status_code=413)
                else:
                    resp = await call_next(request)
            else:
                resp = await call_next(request)
        except Exception as exc:  # never leak internals
            log.error("unhandled %s", type(exc).__name__)
            resp = JSONResponse({"detail": "internal error"}, status_code=500)
        _security_headers(resp, settings, request.url.path)
        route = request.scope.get("route")
        log.info(
            "%s %s -> %s (%.0f ms)",
            request.method,
            getattr(route, "path", "-"),
            resp.status_code,
            (time.monotonic() - t0) * 1000,
        )  # route template only: no query string, no path params
        return resp

    return app


API_PREFIXES = {"api", "auth", "vault", "assets", "healthz"}


def _mount_spa(app: FastAPI, root: Path) -> None:
    """Serve the built React app (same origin => no CORS). Unknown paths fall back to index.html."""
    index = root / "index.html"
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.split("/", 1)[0] in API_PREFIXES:
            raise HTTPException(404, "not found")
        if full_path:
            candidate = root / full_path
            try:
                resolved = candidate.resolve()
                if (
                    resolved.is_file()
                    and resolved.is_relative_to(root)
                    and not candidate.is_symlink()
                ):
                    return FileResponse(resolved)
            except (OSError, ValueError):
                pass
        return FileResponse(index)


def create_app_from_env() -> FastAPI:
    logging.getLogger("waarchive.server").addFilter(RedactingFilter())
    return create_app(Settings.from_env())
