from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from server_support import Env


@pytest.fixture
def web(tmp_path: Path, env_factory: Callable[..., Env]) -> Env:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>spa</title>")
    (root / "assets" / "app-abc123.js").write_text("console.log(1)")
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("TOPSECRET")
    (root / "leak.txt").symlink_to(tmp_path / "secret.txt")
    return env_factory(static_dir=root)


def test_index_and_spa_fallback_are_no_store_with_csp(web: Env) -> None:
    for path in ("/", "/chat/12", "/some/deep/route"):
        r = web.client.get(path)
        assert r.status_code == 200 and "<title>spa</title>" in r.text
        assert (
            r.headers["cache-control"] == "no-store"
            and "frame-ancestors 'none'" in r.headers["content-security-policy"]
        )


def test_hashed_assets_are_cacheable_but_everything_else_is_not(web: Env) -> None:
    r = web.client.get("/assets/app-abc123.js")
    assert (
        r.status_code == 200
        and "immutable" in r.headers["cache-control"]
        and r.headers["x-content-type-options"] == "nosniff"
    )
    assert web.client.get("/favicon.svg").headers["cache-control"] == "no-store"
    assert web.client.get("/assets/missing.js").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/assets/../index.html",
        "/assets/%2e%2e/secret.txt",
        "/%2e%2e/secret.txt",
        "/leak.txt",
        "/..%2fsecret.txt",
        "/assets/..%2f..%2fsecret.txt",
    ],
)
def test_static_traversal_and_symlink_escape_blocked(web: Env, path: str) -> None:
    r = web.client.get(path)
    assert "TOPSECRET" not in r.text


def test_api_prefixes_never_fall_back_to_html(web: Env) -> None:
    for path in ("/api/nope", "/auth/nope", "/vault/nope", "/api"):
        r = web.client.get(path)
        assert r.status_code in (401, 404) and "<title>" not in r.text


def test_spa_is_public_but_data_is_not(web: Env) -> None:
    assert web.client.get("/").status_code == 200
    assert web.client.get("/api/chats").status_code == 401
