"""Google OpenID Connect (authorization-code + PKCE) for a single allow-listed identity."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from .settings import Settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105  # nosec B105 - public URL
ISSUERS = ("https://accounts.google.com", "accounts.google.com")
PENDING_TTL_S = 300
MAX_PENDING = 100


class OIDCError(Exception):
    """Generic by design; details are never shown to the browser."""


class OIDCClient(Protocol):
    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]: ...


def pkce_challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode()
    )


def authorize_url(settings: Settings, *, state: str, nonce: str, verifier: str) -> str:
    q = {
        "client_id": settings.google_client_id or "",
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "prompt": "login",  # force re-authentication; Google's own 2-step/passkey applies
        "max_age": "0",
        "access_type": "online",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(q)}"


def _eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode("utf-8", "replace"), b.encode("utf-8", "replace"))


def validate_claims(claims: dict[str, Any], settings: Settings, *, nonce: str, now: float) -> None:
    """Raise OIDCError unless the claims identify the one allowed, verified identity."""
    try:
        if claims.get("iss") not in ISSUERS:
            raise OIDCError("iss")
        aud = claims.get("aud")
        auds = aud if isinstance(aud, list) else [aud]
        if settings.google_client_id not in auds:
            raise OIDCError("aud")
        if len(auds) > 1 and claims.get("azp") != settings.google_client_id:
            raise OIDCError("azp")
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or exp < now - 30:
            raise OIDCError("exp")
        iat = claims.get("iat")
        if isinstance(iat, (int, float)) and iat > now + 300:
            raise OIDCError("iat")
        if not _eq(str(claims.get("nonce", "")), nonce):
            raise OIDCError("nonce")
        if claims.get("email_verified") is not True:
            raise OIDCError("email_verified")
        email = str(claims.get("email", "")).lower()
        if not _eq(email, (settings.google_allowed_email or "").lower()):
            raise OIDCError("identity")
        if settings.google_allowed_sub and not _eq(
            str(claims.get("sub", "")), settings.google_allowed_sub
        ):
            raise OIDCError("identity")
    except OIDCError:
        raise OIDCError("login rejected") from None


class GoogleOIDC:
    """Exchanges the code at Google's token endpoint over TLS.

    The ID token is received directly from the token endpoint over TLS using our client
    secret, so (per OIDC Core 3.1.3.7) signature verification may be skipped; all claims
    are still validated by `validate_claims`.
    """

    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        self._s = settings
        self._http = http or httpx.Client(timeout=10.0, follow_redirects=False)

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]:
        secret = self._s.google_client_secret
        try:
            r = self._http.post(
                TOKEN_ENDPOINT,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._s.google_client_id or "",
                    "client_secret": secret.get_secret_value() if secret else "",
                    "code_verifier": code_verifier,
                },
            )
            r.raise_for_status()
            token = r.json()["id_token"]
            payload = token.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except (
            httpx.HTTPError,
            KeyError,
            IndexError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            raise OIDCError("token exchange failed") from exc
        if not isinstance(claims, dict):
            raise OIDCError("token exchange failed")
        return claims


@dataclass
class Pending:
    verifier: str
    nonce: str
    binding: str
    expires: float


class PendingStore:
    """One-time OAuth `state` records, bound to the starting browser by a Lax cookie."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._d: dict[str, Pending] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _k(state: str) -> str:
        return hashlib.sha256(state.encode("utf-8", "replace")).hexdigest()

    def put(self, state: str, p: Pending) -> None:
        with self._lock:
            now = self._clock()
            self._d = {k: v for k, v in self._d.items() if v.expires > now}
            if len(self._d) >= MAX_PENDING:
                raise OIDCError("too many pending logins")
            self._d[self._k(state)] = p

    def pop(self, state: str) -> Pending | None:
        with self._lock:
            p = self._d.pop(self._k(state), None)
        if p is None or p.expires < self._clock():
            return None
        return p
