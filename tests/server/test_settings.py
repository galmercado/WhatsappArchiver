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


def test_dev_container_bind_requires_explicit_flag(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        make_settings(tmp_path, host="0.0.0.0")
    assert make_settings(tmp_path, host="0.0.0.0", in_container=True).host == "0.0.0.0"
    with pytest.raises(ValueError, match="loopback"):
        make_settings(
            tmp_path, host="192.168.1.5", in_container=True
        )  # only the wildcard, never a LAN IP


def test_secrets_can_come_from_files(tmp_path: Path) -> None:
    (tmp_path / "pw").write_text(
        "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaGhhc2g\n"
    )
    (tmp_path / "totp").write_text("JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP\n")
    env = {"WA_ARCHIVE_DIR": str(tmp_path), "WA_AUTH_MODE": "password_totp",
           "WA_PASSWORD_HASH_FILE": str(tmp_path / "pw"), "WA_TOTP_SECRET_FILE": str(tmp_path / "totp")}  # fmt: skip
    s = Settings.from_env(env)
    assert (
        s.password_hash == "$argon2id$v=19$m=8,t=1,p=1$c2FsdHNhbHRzYWx0$aGFzaGhhc2hoYXNoaGFzaGhhc2g"
    )
    assert s.totp_secret and s.totp_secret.get_secret_value().endswith("PXP")


def test_secret_file_errors(tmp_path: Path) -> None:
    base = {"WA_ARCHIVE_DIR": str(tmp_path), "WA_AUTH_MODE": "password_totp"}
    with pytest.raises(ConfigError, match="cannot read"):
        Settings.from_env({**base, "WA_PASSWORD_HASH_FILE": str(tmp_path / "missing")})
    (tmp_path / "x").write_text("v")
    with pytest.raises(ConfigError, match="only one"):
        Settings.from_env(
            {**base, "WA_PASSWORD_HASH": "a", "WA_PASSWORD_HASH_FILE": str(tmp_path / "x")}
        )


def test_healthcheck_reports_down_when_nothing_listens(monkeypatch: pytest.MonkeyPatch) -> None:
    from waarchive.server import healthcheck

    monkeypatch.setenv("WA_PORT", "1")
    assert healthcheck.main() == 1


@pytest.mark.parametrize("host", ["unset.invalid", "localhost"])
def test_prod_refuses_placeholder_or_loopback_domains(tmp_path: Path, host: str) -> None:
    with pytest.raises(ValueError, match="real public host"):
        make_settings(tmp_path, env="prod", base_url=f"https://{host}", cookie_secure=True)
