from __future__ import annotations

import logging
import re
from collections.abc import Callable

import pytest

from fixtures import generate_mock_whatsapp as gen
from server_support import BASE, PW, Env

PUBLIC = {"/healthz", "/auth/status", "/auth/login", "/auth/google/start", "/auth/google/callback"}


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.mark.parametrize("mode", ["password_totp", "google"])
def test_every_non_public_route_rejects_anonymous(
    env_factory: Callable[..., Env], mode: str
) -> None:
    env = env_factory(auth_mode=mode)
    checked = 0
    paths = env.ctx_app.openapi()["paths"]  # version-independent route inventory
    assert PUBLIC & set(paths) >= {"/healthz", "/auth/status"}
    for path, ops in paths.items():
        if path in PUBLIC:
            continue
        for method in ops:
            r = env.client.request(
                method.upper(),
                concrete(path),
                json={} if method == "post" else None,
                headers={"Origin": BASE},
            )
            assert r.status_code == 401, (method, path, r.status_code)
            checked += 1
    assert checked == 9  # chats, chat, messages, search, media, avatar, logout, unlock, lock


def test_authenticated_but_locked_returns_423_for_all_data_routes(env: Env) -> None:
    env.login()
    for path in (
        "/api/chats",
        "/api/chats/1",
        "/api/chats/1/messages",
        "/api/search?q=hello",
        "/api/media/12",
    ):
        assert env.client.get(path).status_code == 423, path


def test_no_docs_or_openapi_exposed(env: Env) -> None:
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert env.client.get(p).status_code == 404


def assert_hardened(r) -> None:  # type: ignore[no-untyped-def]
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["cache-control"] == "no-store"
    csp = h["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "default-src" in csp
    assert h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
    assert "server" not in h or "uvicorn" not in h["server"].lower()


def test_security_headers_on_every_response_class(ready: Env) -> None:
    anon = ready.new_client()
    for r in (
        ready.client.get("/healthz"), ready.client.get("/api/chats"), ready.client.get("/api/media/12"),
        ready.client.get("/api/chats/999"), ready.client.get("/nope"), anon.get("/api/chats"),
        anon.post("/auth/login", json={}, headers={"Origin": BASE}), anon.post("/auth/login", json={}),
    ):  # fmt: skip
        assert_hardened(r)


def test_csp_is_strict(env: Env) -> None:
    csp = env.client.get("/healthz").headers["content-security-policy"]
    assert (
        "default-src 'self'" in csp
        and "object-src 'none'" in csp
        and "frame-ancestors 'none'" in csp
    )
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "*" not in csp


def test_hsts_only_in_prod(env: Env, env_factory: Callable[..., Env]) -> None:
    assert "strict-transport-security" not in env.client.get("/healthz").headers
    prod = env_factory(env="prod", base_url="https://archive.example.com", cookie_secure=True)
    r = prod.client.get("/healthz")
    assert "max-age=" in r.headers["strict-transport-security"]


def test_host_header_attack_rejected(env: Env) -> None:
    for host in ("evil.example", "localhost.evil.example", "127.0.0.1.evil.io"):
        r = env.client.get("/healthz", headers={"Host": host})
        assert r.status_code == 400, host
        assert_hardened(r)


def test_cors_not_enabled(ready: Env) -> None:
    r = ready.client.get("/api/chats", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
    pre = ready.client.options(
        "/api/chats",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in pre.headers


def test_errors_do_not_leak_internals(ready: Env) -> None:
    for r in (
        ready.client.get("/api/chats/xyz"),
        ready.client.get("/api/search"),
        ready.client.get("/api/chats", params={"cursor": "!!"}),
    ):
        assert (
            "Traceback" not in r.text and "sqlite" not in r.text.lower() and "/home/" not in r.text
        )


def test_sensitive_content_never_logged(ready: Env, env_factory: Callable[..., Env]) -> None:
    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if not record.name.startswith(
                ("httpx", "httpcore", "asyncio")
            ):  # test-client side loggers
                lines.append(record.getMessage())

    h = H()
    root = logging.getLogger()
    old = root.level
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    try:
        ready.client.get("/api/search", params={"q": "CANARY-SECRET-PHRASE-7731"})
        ready.client.get("/api/chats", params={"q": "Alice Example 15550100101"})
        ready.client.get("/api/chats/1/messages")
        ready.client.get("/api/media/12")
        ready.client.post(
            "/auth/login", json={"password": PW + "x", "totp": "123456"}, headers={"Origin": BASE}
        )
        ready.client.post(
            "/vault/unlock",
            json={"passphrase": "hunter2-passphrase-leak"},
            headers={"Origin": BASE},
        )
        ready.client.get("/api/chats/999")
    finally:
        root.removeHandler(h)
        root.setLevel(old)
    blob = "\n".join(lines)
    assert "GET /api/chats" in blob  # access info is logged (route template + status only)
    for leak in (
        gen.CANARY,
        "Alice",
        "15550100101",
        PW,
        "hunter2",
        "IMG-0001",
        "?q=",
        "wa_session",
        ready.client.headers.get("X-CSRF-Token", "∅"),
    ):
        assert leak not in blob, leak
