from __future__ import annotations

import base64
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from server_support import CLIENT_ID, make_settings
from waarchive.server.oidc import TOKEN_ENDPOINT, GoogleOIDC, OIDCError


def _jwt(claims: dict[str, object]) -> str:
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{b({'alg': 'RS256'})}.{b(claims)}.sig"


def test_exchange_posts_pkce_and_secret_server_side_only(tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["form"] = (
            str(req.url),
            {k: v[0] for k, v in parse_qs(req.content.decode()).items()},
        )
        return httpx.Response(200, json={"id_token": _jwt({"email": "a@b.c", "aud": CLIENT_ID})})

    s = make_settings(tmp_path, auth_mode="google")
    c = GoogleOIDC(s, httpx.Client(transport=httpx.MockTransport(handler)))
    claims = c.exchange(code="abc", code_verifier="ver", redirect_uri=s.google_redirect_uri)
    assert claims["email"] == "a@b.c" and seen["url"] == TOKEN_ENDPOINT
    form = seen["form"]
    assert (
        isinstance(form, dict)
        and form["code_verifier"] == "ver"
        and form["client_secret"] == "s3cret"
    )
    assert form["grant_type"] == "authorization_code" and form["client_id"] == CLIENT_ID


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(400, json={"error": "invalid_grant"}),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"id_token": "x"}),
        httpx.Response(200, json={"id_token": "a.!!!.c"}),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"id_token": 5}),
    ],
)
def test_exchange_failures_are_generic(tmp_path: Path, resp: httpx.Response) -> None:
    s = make_settings(tmp_path, auth_mode="google")
    c = GoogleOIDC(s, httpx.Client(transport=httpx.MockTransport(lambda _r: resp)))
    with pytest.raises(OIDCError, match="token exchange failed"):
        c.exchange(code="abc", code_verifier="v", redirect_uri="x")


def test_network_error_is_generic(tmp_path: Path) -> None:
    def boom(_r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    c = GoogleOIDC(
        make_settings(tmp_path, auth_mode="google"),
        httpx.Client(transport=httpx.MockTransport(boom)),
    )
    with pytest.raises(OIDCError):
        c.exchange(code="a", code_verifier="v", redirect_uri="x")
