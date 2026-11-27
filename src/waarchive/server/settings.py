"""Runtime configuration, loaded from environment variables (WA_*). No defaults for secrets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import pyotp
from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
WILDCARD = "0.0.0.0"  # noqa: S104  # nosec B104 - accepted only with WA_IN_CONTAINER; port published to 127.0.0.1


class ConfigError(Exception):
    pass


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    env: Literal["dev", "prod"] = "dev"
    archive_dir: Path
    auth_mode: Literal["google", "password_totp"]
    base_url: str = "http://localhost:8000"
    host: str = "127.0.0.1"
    port: int = 8000
    trust_proxy: bool = False
    static_dir: Path | None = None
    in_container: bool = (
        False  # dev only: bind 0.0.0.0 *inside* a container whose port is published to 127.0.0.1
    )
    cookie_secure: bool = False

    session_idle_s: int = 900
    session_max_s: int = 12 * 3600
    vault_idle_s: int = 1800

    # brute-force protection (per-IP strict, global lenient)
    ip_free_attempts: int = 3
    global_free_attempts: int = 20
    backoff_base_s: float = 2.0
    backoff_max_s: float = 900.0

    # google mode
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_allowed_email: str | None = None
    google_allowed_sub: str | None = None

    # password + TOTP mode
    password_hash: str | None = None
    totp_secret: SecretStr | None = None

    @property
    def origin(self) -> str:
        u = urlsplit(self.base_url)
        return f"{u.scheme}://{u.netloc}"

    @property
    def hostname(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    @property
    def allowed_hosts(self) -> list[str]:
        hosts = {self.hostname}
        if self.env == "dev":
            hosts |= {"localhost", "127.0.0.1"}
        return sorted(h for h in hosts if h)

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.base_url.rstrip('/')}/auth/google/callback"

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        u = urlsplit(self.base_url)
        if u.scheme not in ("http", "https") or not u.hostname or u.path not in ("", "/"):
            raise ValueError("WA_BASE_URL must be a bare http(s) origin")
        if (
            self.env == "dev"
            and self.host not in LOOPBACK
            and not (self.in_container and self.host == WILDCARD)
        ):
            raise ValueError("dev mode must bind to loopback only")
        if self.env == "prod":
            if u.scheme != "https" or not self.cookie_secure:
                raise ValueError("prod requires an https WA_BASE_URL and secure cookies")
            if (u.hostname or "").endswith(".invalid") or u.hostname in LOOPBACK:
                raise ValueError("set WA_DOMAIN to the real public host name")
        elif u.scheme == "http" and u.hostname not in LOOPBACK:
            raise ValueError("plain http is only allowed for localhost")
        if self.auth_mode == "google":
            need = (self.google_client_id, self.google_client_secret, self.google_allowed_email)
            if not all(need):
                raise ValueError(
                    "google mode needs WA_GOOGLE_CLIENT_ID, WA_GOOGLE_CLIENT_SECRET, "
                    "WA_GOOGLE_ALLOWED_EMAIL"
                )
        elif not (self.password_hash and self.totp_secret):
            raise ValueError("password_totp mode needs WA_PASSWORD_HASH and WA_TOTP_SECRET")
        else:
            if not self.password_hash.startswith("$argon2id$"):
                raise ValueError("WA_PASSWORD_HASH must be an argon2id hash (see setup_auth)")
            try:
                pyotp.TOTP(self.totp_secret.get_secret_value()).byte_secret()
            except Exception as exc:
                raise ValueError("WA_TOTP_SECRET must be base32 with at least 112 bits") from exc
        if self.session_idle_s < 60 or self.session_max_s < self.session_idle_s:
            raise ValueError("invalid session timeouts")
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        e = environ if environ is not None else os.environ

        def g(name: str) -> str | None:
            """WA_<NAME>, or the contents of the file named by WA_<NAME>_FILE (Docker/K8s secrets)."""
            path = e.get(f"WA_{name}_FILE")
            if path:
                try:
                    text = Path(path).read_text(encoding="utf-8").strip()
                except OSError as exc:
                    raise ConfigError(f"cannot read WA_{name}_FILE") from exc
                if e.get(f"WA_{name}"):
                    raise ConfigError(f"set only one of WA_{name} and WA_{name}_FILE")
                return text or None
            v = e.get(f"WA_{name}")
            return v if v else None

        def b(name: str, default: bool) -> bool:
            v = g(name)
            return default if v is None else v.lower() in ("1", "true", "yes")

        env = g("ENV") or "dev"
        archive = g("ARCHIVE_DIR")
        mode = g("AUTH_MODE")
        if not archive or not mode:
            raise ConfigError("WA_ARCHIVE_DIR and WA_AUTH_MODE are required")
        data: dict[str, object] = {
            "env": env,
            "archive_dir": Path(archive),
            "auth_mode": mode,
            "cookie_secure": b("COOKIE_SECURE", env == "prod"),
            "trust_proxy": b("TRUST_PROXY", False),
            "in_container": b("IN_CONTAINER", False),
        }
        for key, name in (
            ("base_url", "BASE_URL"),
            ("host", "HOST"),
            ("static_dir", "STATIC_DIR"),
            ("google_client_id", "GOOGLE_CLIENT_ID"),
            ("google_client_secret", "GOOGLE_CLIENT_SECRET"),
            ("google_allowed_email", "GOOGLE_ALLOWED_EMAIL"),
            ("google_allowed_sub", "GOOGLE_ALLOWED_SUB"),
            ("password_hash", "PASSWORD_HASH"),
            ("totp_secret", "TOTP_SECRET"),
        ):
            if (v := g(name)) is not None:
                data[key] = v
        for key, name in (
            ("port", "PORT"),
            ("session_idle_s", "SESSION_IDLE_S"),
            ("vault_idle_s", "VAULT_IDLE_S"),
        ):
            if (v := g(name)) is not None:
                data[key] = int(v)
        try:
            return cls.model_validate(data)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
