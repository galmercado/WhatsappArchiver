"""Regression tests for the deployment files: a careless edit must not silently weaken the posture."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict[str, Any]:
    data = yaml.safe_load((ROOT / name).read_text())
    assert isinstance(data, dict)
    return data


COMPOSE = load("docker-compose.yml")
SERVICES: dict[str, dict[str, Any]] = COMPOSE["services"]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
CADDY = (ROOT / "deploy" / "Caddyfile").read_text()
WORKFLOW_TEXT = (ROOT / ".github/workflows/test-and-security.yml").read_text()
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)


# ----------------------------------------------------------------------------- compose
def test_dev_profile_publishes_only_on_loopback() -> None:
    ports = SERVICES["app-dev"]["ports"]
    assert ports and all(str(p).startswith("127.0.0.1:") for p in ports)
    assert SERVICES["app-dev"]["environment"]["WA_ENV"] == "dev"


def test_prod_app_publishes_nothing_and_sits_on_an_internal_network() -> None:
    app = SERVICES["app"]
    assert "ports" not in app and app["expose"] == ["8000"]
    assert app["networks"] == ["backend"]
    assert COMPOSE["networks"]["backend"]["internal"] is True  # no internet route by default
    assert (
        app["environment"]["WA_ENV"] == "prod" and app["environment"]["WA_COOKIE_SECURE"] == "true"
    )


@pytest.mark.parametrize("name", ["app", "app-dev", "caddy", "cloudflared", "tailscale"])
def test_every_service_is_locked_down(name: str) -> None:
    s = SERVICES[name]
    assert s["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in s["security_opt"]
    assert "privileged" not in s and "network_mode" not in s
    assert not any("docker.sock" in str(v) for v in s.get("volumes", []))


@pytest.mark.parametrize("name", ["app", "app-dev"])
def test_app_runs_unprivileged_read_only_with_archive_mounted_ro(name: str) -> None:
    s = SERVICES[name]
    assert s["read_only"] is True and s["user"] == "10001:10001"
    assert s["pids_limit"] and s["mem_limit"]
    archive_mounts = [v for v in s["volumes"] if str(v).endswith(":/data:ro")]
    assert archive_mounts, "archive must be mounted read-only"


def test_caddy_is_the_only_public_listener() -> None:
    assert {n for n, s in SERVICES.items() if "ports" in s and n != "app-dev"} == {"caddy"}
    assert SERVICES["caddy"]["cap_add"] == ["NET_BIND_SERVICE"]


def test_images_are_pinned_not_latest() -> None:
    for name, s in SERVICES.items():
        image = s.get("image", "")
        if name in ("app", "app-dev"):
            continue  # built locally
        assert ":" in image and not image.endswith(":latest"), name


def test_no_secrets_in_compose_or_env_example() -> None:
    text = (ROOT / "docker-compose.yml").read_text() + (ROOT / ".env.example").read_text()
    assert not re.search(r"\$argon2|JBSWY3DP|GOCSPX|-----BEGIN", text)
    for override in ("docker-compose.password.yml", "docker-compose.google.yml"):
        o = load(override)
        for svc in o["services"].values():
            env = svc["environment"]
            assert not any(
                k in env for k in ("WA_PASSWORD_HASH", "WA_TOTP_SECRET", "WA_GOOGLE_CLIENT_SECRET")
            )
            assert any(
                k.endswith("_FILE") for k in env
            )  # secrets arrive as files under /run/secrets
        assert all(s["file"].startswith("./secrets/") for s in o["secrets"].values())


def test_only_google_override_gives_the_app_internet_egress() -> None:
    assert load("docker-compose.google.yml")["services"]["app"]["networks"] == ["backend", "egress"]
    assert "egress" not in load("docker-compose.password.yml")["services"]["app"].get(
        "networks", []
    )


def test_secrets_directory_is_never_committed() -> None:
    gi = (ROOT / ".gitignore").read_text()
    assert "secrets/*" in gi and ".env" in gi
    assert "secrets" in (ROOT / ".dockerignore").read_text()


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")
@pytest.mark.parametrize("override", ["docker-compose.password.yml", "docker-compose.google.yml"])
@pytest.mark.parametrize("profile", ["dev", "prod", "tunnel", "tailscale"])
def test_compose_config_is_valid_for_every_profile(override: str, profile: str) -> None:
    import os

    env = {**os.environ, "WA_AUTH_MODE": "password_totp", "COMPOSE_FILE": ""}
    r = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "-f", override, "--profile", profile, "config", "-q"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr


# --------------------------------------------------------------------------- Dockerfile
def test_dockerfile_is_multistage_non_root_with_healthcheck() -> None:
    assert re.findall(r"^FROM .* AS (\w+)$", DOCKERFILE, re.M) == ["web", "base", "dev", "runtime"]
    final = DOCKERFILE.split("AS runtime", 1)[1]
    assert "USER 10001:10001" in final and "HEALTHCHECK" in final
    assert 'CMD ["python", "-m", "waarchive.server"]' in final
    assert "--reload" not in final  # hot reload never ships in the prod image
    assert not re.search(
        r"^FROM \S+:latest|--no-check-certificate|curl[^\n]*\|\s*(ba)?sh|ADD https?://",
        DOCKERFILE,
        re.M,
    )
    assert "npm ci --ignore-scripts" in DOCKERFILE


# ---------------------------------------------------------------------------- Caddyfile
def test_caddyfile_security_posture() -> None:
    assert "Strict-Transport-Security" in CADDY and "max-age=63072000" in CADDY
    assert "request_body" in CADDY and "max_size 64KB" in CADDY
    assert "@badmethod not method GET HEAD POST" in CADDY and "respond @badmethod 405" in CADDY
    assert "respond @internal 404" in CADDY  # /healthz is not public
    assert "header_up X-Forwarded-For {remote_host}" in CADDY  # replaced, never appended
    # privacy: request URIs (search terms, ids), headers (cookies) and client IPs are never logged
    for field in (
        "request>uri delete",
        "request>headers delete",
        "request>remote_ip delete",
        "request>client_ip delete",
    ):
        assert field in CADDY
    # compression only for static assets (BREACH): the `encode` directive must be scoped to @static
    encodes = re.findall(r"^\s*encode\s+(\S+)", CADDY, re.M)
    assert encodes == ["@static"]
    assert "tls internal" not in CADDY and "http://" not in CADDY.split("reverse_proxy")[0]


# ------------------------------------------------------------------------------ workflow
def test_workflow_is_least_privilege_and_runs_every_gate() -> None:
    assert WORKFLOW["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in WORKFLOW_TEXT and "secrets.GITHUB_TOKEN" in WORKFLOW_TEXT
    assert WORKFLOW_TEXT.count("persist-credentials: false") >= 5
    for gate in ("ruff check", "ruff format --check", "mypy", "bandit", "pytest", "pip-audit", "npm run typecheck",
                 "eslint", "npm test", "npm run audit", "npm run test:e2e", "trivy", "gitleaks", "cov-fail-under"):  # fmt: skip
        assert gate in WORKFLOW_TEXT, gate
    assert set(WORKFLOW["jobs"]) == {"python", "web", "e2e", "docker", "secrets"}
    assert WORKFLOW["jobs"]["e2e"]["needs"] == ["python", "web"]
    # hard gates must not be silently optional; only the informational dev-tool audit may continue-on-error
    assert WORKFLOW_TEXT.count("continue-on-error") == 1
