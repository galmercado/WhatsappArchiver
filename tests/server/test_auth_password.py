from __future__ import annotations

from collections.abc import Callable

from archive_factory import PASSPHRASE
from server_support import BASE, PW, Env

H = {"Origin": BASE}


def login(env: Env, password: str = PW, totp: str | None = None):  # type: ignore[no-untyped-def]
    return env.client.post(
        "/auth/login", json={"password": password, "totp": totp or env.totp()}, headers=H
    )


def test_login_success_sets_hardened_cookie(env: Env) -> None:
    r = login(env)
    assert r.status_code == 200 and r.json()["csrf_token"]
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc and "path=/" in sc and "domain" not in sc
    assert "max-age" not in sc and "expires" not in sc  # session cookie


def test_cookie_secure_and_host_prefix_when_secure(env_factory: Callable[..., Env]) -> None:
    e = env_factory(cookie_secure=True)
    r = login(e)
    assert (
        r.headers["set-cookie"].startswith("__Host-wa_session=")
        and "secure" in r.headers["set-cookie"].lower()
    )


def test_wrong_credentials_are_indistinguishable(env: Env) -> None:
    bodies = {
        login(env, password="nope-nope-nope").text,
        login(env, totp="000000").text,
        login(env, password="x", totp="111111").text,
    }
    assert len(bodies) == 1 and "invalid credentials" in bodies.pop()


def test_failed_login_never_issues_cookie(env: Env) -> None:
    r = login(env, password="wrong")
    assert r.status_code == 401 and "set-cookie" not in r.headers


def test_totp_replay_rejected_and_window(env: Env) -> None:
    code = env.totp()
    assert login(env, totp=code).status_code == 200
    env.client.cookies.clear()
    assert login(env, totp=code).status_code == 401  # same step cannot be reused
    env.clock.advance(30)
    assert login(env, totp=env.totp(-1)).status_code == 401  # older than last used
    assert login(env, totp=env.totp(1)).status_code == 200  # +1 step window allowed


def test_totp_far_outside_window_rejected(env: Env) -> None:
    assert login(env, totp=env.totp(5)).status_code == 401
    assert login(env, totp=env.totp(-5)).status_code == 401


def test_bruteforce_backoff_is_exponential_and_blocks_correct_creds(env: Env) -> None:
    for _ in range(4):  # 3 free failures; the 4th triggers the first lockout
        assert login(env, password="bad").status_code == 401
    waits = []
    for _ in range(3):
        r = login(env, password="bad")
        assert r.status_code == 429
        waits.append(int(r.headers["retry-after"]))
        env.clock.advance(waits[-1])  # wait it out, then fail again
        assert login(env, password="bad").status_code == 401
    assert waits[0] < waits[1] < waits[2]
    assert login(env).status_code == 429  # correct credentials still locked during backoff


def test_backoff_expires_and_success_resets(env: Env) -> None:
    for _ in range(4):
        login(env, password="bad")
    env.clock.advance(3)
    assert login(env).status_code == 200


def test_session_fixation_new_id_each_login(env: Env) -> None:
    login(env)
    first = env.client.cookies.get("wa_session")
    env.clock.advance(31)
    env.client.cookies.clear()
    env.client.cookies.set("wa_session", "attacker-chosen-id", domain="localhost")
    r = login(env)
    issued = r.headers["set-cookie"].split("=", 1)[1].split(";", 1)[0]
    assert issued not in ("attacker-chosen-id", first) and len(issued) >= 40
    assert env.ctx.sessions.get("attacker-chosen-id") is None  # never adopted


def test_forged_session_cookie_rejected(env: Env) -> None:
    env.client.cookies.set("wa_session", "A" * 43)
    assert env.client.get("/api/chats").status_code == 401


def test_idle_and_absolute_timeouts(env: Env) -> None:
    login(env)
    env.clock.advance(env.settings.session_idle_s - 5)
    assert env.client.get("/auth/status").json()["authenticated"]  # activity resets idle
    env.clock.advance(env.settings.session_idle_s + 1)
    assert not env.client.get("/auth/status").json()["authenticated"]
    env.clock.advance(31)
    login(env)
    started = env.clock.t
    for _ in range(100):  # stay active, but absolute lifetime still ends the session
        env.clock.advance(env.settings.session_idle_s - 10)
        env.client.get("/auth/status")
        if env.clock.t > started + env.settings.session_max_s + 100:
            break
    assert not env.client.get("/auth/status").json()["authenticated"]


def test_csrf_and_origin_enforced(env: Env) -> None:
    csrf = login(env).json()["csrf_token"]
    body = {"passphrase": PASSPHRASE}
    assert env.client.post("/vault/unlock", json=body, headers=H).status_code == 403  # no token
    assert (
        env.client.post(
            "/vault/unlock", json=body, headers={**H, "X-CSRF-Token": "wrong"}
        ).status_code
        == 403
    )
    assert (
        env.client.post("/vault/unlock", json=body, headers={"X-CSRF-Token": csrf}).status_code
        == 403
    )  # no Origin
    evil = {"Origin": "http://evil.example", "X-CSRF-Token": csrf}
    assert env.client.post("/vault/unlock", json=body, headers=evil).status_code == 403
    assert (
        env.client.post("/vault/unlock", json=body, headers={**H, "X-CSRF-Token": csrf}).status_code
        == 200
    )


def test_login_requires_matching_origin(env: Env) -> None:
    r = env.client.post(
        "/auth/login",
        json={"password": PW, "totp": env.totp()},
        headers={"Origin": "http://evil.example"},
    )
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_logout_ends_session(env: Env) -> None:
    csrf = login(env).json()["csrf_token"]
    assert env.client.post("/auth/logout", headers={**H, "X-CSRF-Token": csrf}).status_code == 200
    assert env.client.get("/api/chats").status_code == 401


def test_validation_errors_do_not_echo_secrets(env: Env) -> None:
    r = env.client.post(
        "/auth/login", json={"password": PW, "totp": "not-digits", "extra": 1}, headers=H
    )
    assert r.status_code == 422 and PW not in r.text and "not-digits" not in r.text


def test_mode_isolation_only_configured_auth_routes(env_factory: Callable[..., Env]) -> None:
    pw = env_factory()
    assert pw.client.get("/auth/google/start", follow_redirects=False).status_code == 404
    g = env_factory(auth_mode="google")
    assert (
        g.client.post(
            "/auth/login", json={"password": "x", "totp": "123456"}, headers=H
        ).status_code
        == 404
    )


def test_oversize_body_rejected(env: Env) -> None:
    r = env.client.post(
        "/auth/login", content=b"x" * 70_000, headers={**H, "Content-Type": "application/json"}
    )
    assert r.status_code == 413


def test_totp_replay_state_is_not_consumed_by_wrong_password(env: Env) -> None:
    code = env.totp()
    assert login(env, password="wrong", totp=code).status_code == 401
    assert login(env, totp=code).status_code == 200
