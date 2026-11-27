from __future__ import annotations

from pathlib import Path

import pytest

from server_support import make_settings
from waarchive.server.settings import ConfigError, Settings


def test_dev_must_bind_loopback(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        make_settings(tmp_path, host="0.0.0.0")


def test_plain_http_only_for_localhost(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="plain http"):
        make_settings(tmp_path, base_url="http://archive.example.com")


def test_prod_requires_https_and_secure_cookies(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="https"):
        make_settings(tmp_path, env="prod", base_url="http://localhost:8000")
    with pytest.raises(ValueError, match="secure cookies"):
        make_settings(
            tmp_path, env="prod", base_url="https://archive.example.com", cookie_secure=False
        )
    s = make_settings(
        tmp_path, env="prod", base_url="https://archive.example.com", cookie_secure=True
    )
    assert s.allowed_hosts == ["archive.example.com"]


def test_weak_secrets_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="argon2id"):
        make_settings(tmp_path, password_hash="plaintext")
    with pytest.raises(ValueError, match="112 bits"):
        make_settings(tmp_path, totp_secret="JBSWY3DP")


def test_from_env_and_missing_values(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({})
    with pytest.raises(ConfigError):
        Settings.from_env({"WA_ARCHIVE_DIR": str(tmp_path), "WA_AUTH_MODE": "google"})
    s = Settings.from_env({
        "WA_ARCHIVE_DIR": str(tmp_path), "WA_AUTH_MODE": "google", "WA_GOOGLE_CLIENT_ID": "id",
        "WA_GOOGLE_CLIENT_SECRET": "hunter2-xyz", "WA_GOOGLE_ALLOWED_EMAIL": "me@example.com",
    })  # fmt: skip
    assert s.auth_mode == "google" and "hunter2" not in repr(s)  # SecretStr never printed
