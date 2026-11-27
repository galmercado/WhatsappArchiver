from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from server_support import BASE, CLIENT_ID, EMAIL, SUB, Env
from waarchive.server import oidc
from waarchive.server.settings import Settings


@pytest.fixture
def g(env_factory: Callable[..., Env]) -> Env:
    return env_factory(auth_mode="google")


def claims(nonce_: str, env: Env, **over: Any) -> dict[str, Any]:
    nonce = nonce_
    now = env.clock.wall()
    base = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "exp": now + 3000, "iat": now,
            "nonce": nonce, "email": EMAIL, "email_verified": True, "sub": SUB}  # fmt: skip
    base.update(over)
    return base


def start(client: TestClient) -> dict[str, str]:
    r = client.get("/auth/google/start", follow_redirects=False)
    assert r.status_code == 302
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    q["_loc"] = r.headers["location"]
    q["_setcookie"] = r.headers["set-cookie"]
    return q


def callback(client: TestClient, state: str, code: str = "authcode"):  # type: ignore[no-untyped-def]
    return client.get(
        "/auth/google/callback", params={"code": code, "state": state}, follow_redirects=False
    )


def test_start_builds_secure_authorization_request(g: Env) -> None:
    q = start(g.client)
    assert q["_loc"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert (
        q["client_id"] == CLIENT_ID
        and q["response_type"] == "code"
        and q["scope"] == "openid email"
    )
    assert q["redirect_uri"] == "http://localhost:8000/auth/google/callback"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["prompt"] == "login" and q["max_age"] == "0"
    assert len(q["state"]) >= 40 and len(q["nonce"]) >= 40 and q["state"] != q["nonce"]
    sc = q["_setcookie"].lower()
    assert (
        "httponly" in sc
        and "samesite=lax" in sc
        and "path=/auth/google" in sc
        and "max-age=300" in sc
    )
    assert "s3cret" not in q["_loc"]  # client secret never goes through the browser


def test_full_login_success(g: Env) -> None:
    q = start(g.client)
    g.oidc.claims = claims(q["nonce"], g)
    r = callback(g.client, q["state"])
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert (
        "wa_session=" in r.headers["set-cookie"]
        and "samesite=strict" in r.headers["set-cookie"].lower()
    )
    # PKCE: the verifier sent to the token endpoint hashes to the challenge from the start request
    assert oidc.pkce_challenge(g.oidc.calls[0]["verifier"]) == q["code_challenge"]
    assert g.oidc.calls[0]["redirect"] == "http://localhost:8000/auth/google/callback"
    st = g.client.get("/auth/status").json()
    assert st["authenticated"] and st["csrf_token"]
    csrf = st["csrf_token"]
    assert g.unlock(csrf).status_code == 200  # vault passphrase is still required
    assert g.client.get("/api/chats").status_code == 200


def test_state_is_single_use(g: Env) -> None:
    q = start(g.client)
    g.oidc.claims = claims(q["nonce"], g)
    assert callback(g.client, q["state"]).headers["location"] == "/"
    g.client.cookies.delete("wa_session")
    r = callback(g.client, q["state"])
    assert r.headers["location"] == "/?login=failed"


@pytest.mark.parametrize(
    "over",
    [
        {"email": "attacker@example.com"},
        {"email": "OWNER@EXAMPLE.COM.evil.io"},
        {"email_verified": False},
        {"email_verified": "true"},
        {"sub": "999"},
        {"iss": "https://evil.example"},
        {"aud": "other-client"},
        {"aud": [CLIENT_ID, "x"], "azp": "x"},
        {"exp": 1.0},
        {"nonce": "wrong"},
        {"iat": 9e12},
    ],
)
def test_bad_claims_rejected(g: Env, over: dict[str, Any]) -> None:
    q = start(g.client)
    g.oidc.claims = claims(q["nonce"], g, **over)
    r = callback(g.client, q["state"])
    assert r.headers["location"] == "/?login=failed" and "wa_session" not in r.headers.get(
        "set-cookie", ""
    )
    assert g.client.get("/api/chats").status_code == 401


def test_non_ascii_claims_do_not_crash(g: Env) -> None:
    q = start(g.client)
    g.oidc.claims = claims(q["nonce"], g, email="ow\u00f1er@example.com", sub="\u2603")
    assert callback(g.client, q["state"]).headers["location"] == "/?login=failed"


def test_email_case_insensitive_match_ok(g: Env) -> None:
    q = start(g.client)
    g.oidc.claims = claims(q["nonce"], g, email=EMAIL.upper())
    assert callback(g.client, q["state"]).headers["location"] == "/"


def test_missing_binding_cookie_rejected_login_csrf(g: Env) -> None:
    q = start(g.client)
    g.oidc.claims = claims(q["nonce"], g)
    other = g.new_client()  # attacker-supplied link followed by a different browser
    assert callback(other, q["state"]).headers["location"] == "/?login=failed"
    assert other.get("/auth/status").json()["authenticated"] is False


def test_unknown_state_error_param_and_missing_code(g: Env) -> None:
    assert callback(g.client, "never-issued").headers["location"] == "/?login=failed"
    q = start(g.client)
    r = g.client.get(
        "/auth/google/callback",
        params={"error": "access_denied", "state": q["state"]},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/?login=failed"
    assert (
        g.client.get("/auth/google/callback", follow_redirects=False).headers["location"]
        == "/?login=failed"
    )


def test_pending_state_expires(g: Env) -> None:
    q = start(g.client)
    g.oidc.claims = claims(q["nonce"], g)
    g.clock.advance(oidc.PENDING_TTL_S + 1)
    assert callback(g.client, q["state"]).headers["location"] == "/?login=failed"


def test_token_exchange_failure_is_generic(g: Env) -> None:
    q = start(g.client)
    g.oidc.fail = True
    r = callback(g.client, q["state"])
    assert r.status_code == 303 and r.headers["location"] == "/?login=failed"


def test_callback_failures_trigger_backoff(g: Env) -> None:
    for _ in range(4):
        callback(g.client, "bogus")
    r = callback(g.client, "bogus")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_pending_store_is_bounded(g: Env) -> None:
    for _ in range(oidc.MAX_PENDING):
        assert g.new_client().get("/auth/google/start", follow_redirects=False).status_code == 302
    assert g.new_client().get("/auth/google/start", follow_redirects=False).status_code in (
        302,
        429,
    )


def test_validate_claims_pure(g: Env) -> None:
    s: Settings = g.settings
    ok = claims("n", g)
    oidc.validate_claims(ok, s, nonce="n", now=g.clock.wall())
    with pytest.raises(oidc.OIDCError):
        oidc.validate_claims({**ok, "email": "x@y.z"}, s, nonce="n", now=g.clock.wall())
    with pytest.raises(oidc.OIDCError):
        oidc.validate_claims(
            {k: v for k, v in ok.items() if k != "nonce"}, s, nonce="n", now=g.clock.wall()
        )


def test_google_mode_requires_pinned_identity_settings(tmp_path: Any) -> None:
    from server_support import make_settings

    with pytest.raises(ValueError, match="google mode needs"):
        Settings(archive_dir=tmp_path, auth_mode="google", base_url=BASE)
    s = make_settings(tmp_path, auth_mode="google")
    assert s.google_redirect_uri == "http://localhost:8000/auth/google/callback"
