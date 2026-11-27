from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyotp
import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from archive_factory import PASSPHRASE, make_archive
from waarchive.server.app import create_app
from waarchive.server.context import AppContext
from waarchive.server.settings import Settings

PW = "S3cure-test-password!"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
BASE = "http://localhost:8000"
WALL0 = 1_800_000_000.0
EMAIL = "owner@example.com"
SUB = "1234567890"
CLIENT_ID = "test-client.apps.googleusercontent.com"
_HASH = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PW)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def wall(self) -> float:
        return WALL0 + self.t

    def advance(self, s: float) -> None:
        self.t += s


class FakeOIDC:
    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}
        self.calls: list[dict[str, str]] = []
        self.fail = False

    def exchange(self, *, code: str, code_verifier: str, redirect_uri: str) -> dict[str, Any]:
        from waarchive.server.oidc import OIDCError

        self.calls.append({"code": code, "verifier": code_verifier, "redirect": redirect_uri})
        if self.fail:
            raise OIDCError("x")
        return dict(self.claims)


def make_settings(archive: Path, **over: Any) -> Settings:
    base: dict[str, Any] = {
        "archive_dir": archive, "auth_mode": "password_totp", "base_url": BASE,
        "password_hash": _HASH, "totp_secret": TOTP_SECRET,
    }  # fmt: skip
    if over.get("auth_mode") == "google":
        base.update(google_client_id=CLIENT_ID, google_client_secret="s3cret", google_allowed_email=EMAIL,
                    google_allowed_sub=SUB, password_hash=None, totp_secret=None)  # fmt: skip
    base.update(over)
    return Settings(**base)


@dataclass
class Env:
    client: TestClient
    ctx: AppContext
    clock: Clock
    settings: Settings
    archive: Path
    oidc: FakeOIDC
    ctx_app: Any = None

    def totp(self, offset: int = 0) -> str:
        return pyotp.TOTP(TOTP_SECRET).at(int(self.clock.wall() // 30 + offset) * 30)

    def login(self, client: TestClient | None = None) -> str:
        c = client or self.client
        r = c.post(
            "/auth/login", json={"password": PW, "totp": self.totp()}, headers={"Origin": BASE}
        )
        assert r.status_code == 200, r.text
        return str(r.json()["csrf_token"])

    def unlock(
        self, csrf: str, passphrase: str = PASSPHRASE, client: TestClient | None = None
    ) -> Any:
        return (client or self.client).post(
            "/vault/unlock",
            json={"passphrase": passphrase},
            headers={"Origin": BASE, "X-CSRF-Token": csrf},
        )

    def ready(self) -> str:
        """Logged in + unlocked; returns the CSRF token."""
        self.clock.advance(31)  # fresh TOTP step each time (replay protection)
        csrf = self.login()
        assert self.unlock(csrf).status_code == 200
        return csrf

    def new_client(self) -> TestClient:
        return TestClient(self.client.app, base_url=BASE)


@pytest.fixture(scope="session")
def archive_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_archive(tmp_path_factory.mktemp("srv"))


@pytest.fixture
def env_factory(archive_dir: Path) -> Iterator[Callable[..., Env]]:
    clients: list[TestClient] = []

    def build(**over: Any) -> Env:
        clock, fake = Clock(), FakeOIDC()
        settings = make_settings(archive_dir, **over)
        app = create_app(settings, oidc_client=fake if settings.auth_mode == "google" else None,
                         clock=clock, wall=clock.wall)  # fmt: skip
        client = TestClient(app, base_url=settings.base_url)
        clients.append(client)
        return Env(client, app.state.ctx, clock, settings, archive_dir, fake, app)

    yield build
    for c in clients:
        c.app.state.ctx.lock_everything()  # type: ignore[attr-defined]
        c.close()


@pytest.fixture
def env(env_factory: Callable[..., Env]) -> Env:
    return env_factory()


@pytest.fixture
def ready(env: Env) -> Env:
    env.client.headers["X-CSRF-Token"] = env.ready()
    return env
