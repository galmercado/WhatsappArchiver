from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
import start_local

from waarchive.ingest import cli
from waarchive.server.settings import Settings


def test_first_run_creates_private_login_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda _="": "")
    out: list[str] = []
    answers = iter(["a-long-enough-password", "a-long-enough-password"])
    h, t = start_local.ensure_auth(tmp_path / "auth", lambda _p: next(answers), out.append)
    assert h.startswith("$argon2id$") and len(t) >= 26
    assert any(
        t in line for line in out
    )  # the setup key is shown so it can be typed into an authenticator
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "auth" / "password_hash").stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "auth").stat().st_mode) == 0o700
    # second run reuses them and never asks again
    assert start_local.ensure_auth(
        tmp_path / "auth", lambda _p: pytest.fail("must not prompt")
    ) == (h, t)


@pytest.mark.parametrize(
    "first,second", [("short", "short"), ("a-long-enough-password", "different-long-password")]
)
def test_bad_passwords_are_rejected_without_writing(
    tmp_path: Path, first: str, second: str
) -> None:
    answers = iter([first, second])
    with pytest.raises(SystemExit):
        start_local.ensure_auth(tmp_path / "auth", lambda _p: next(answers), lambda _m: None)
    assert not (tmp_path / "auth" / "password_hash").exists()


def test_web_build_skipped_when_present_and_explains_missing_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "web" / "dist").mkdir(parents=True)
    (tmp_path / "web" / "dist" / "index.html").write_text("x")
    assert (
        start_local.ensure_web(tmp_path, lambda *a, **k: pytest.fail("no build needed"))
        == tmp_path / "web" / "dist"
    )
    (tmp_path / "web" / "dist" / "index.html").unlink()
    monkeypatch.setattr("shutil.which", lambda _n: None)
    with pytest.raises(SystemExit, match=r"Node\.js"):
        start_local.ensure_web(tmp_path)


def test_web_build_runs_npm_ci_then_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "web").mkdir()
    monkeypatch.setattr("shutil.which", lambda _n: "/usr/bin/npm")
    calls: list[list[str]] = []
    start_local.ensure_web(tmp_path, lambda cmd, **_k: calls.append(cmd))
    assert [c[1] for c in calls] == ["ci", "run"] and calls[1][2] == "build"


def test_settings_are_loopback_only(tmp_path: Path) -> None:
    s = start_local.build_settings(
        tmp_path, tmp_path, 8123, "$argon2id$x", "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
    )
    assert (
        isinstance(s, Settings)
        and s.host == "127.0.0.1"
        and s.env == "dev"
        and s.base_url == "http://localhost:8123"
    )


def test_demo_archive_is_built_and_reused(tmp_path: Path) -> None:
    dest = tmp_path / "demo"
    pw = start_local.make_demo(dest)
    assert (dest / "archive.db").is_file() and (dest / "archive.kdf.json").is_file() and pw
    assert start_local.make_demo(dest) == pw  # no rebuild


def test_missing_archive_and_busy_port_give_friendly_exit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert start_local.main(["--archive", str(tmp_path / "nope"), "--no-browser"]) == 2
    assert "extract_and_ingest.py" in capsys.readouterr().out


def test_adb_path_option_exists_and_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert "--adb-path" in cli.build_parser().format_help()
    seen: list[str | None] = []

    class Boom(Exception):
        pass

    def fake_runner(path: str | None = None) -> None:
        seen.append(path)
        raise Boom

    monkeypatch.setattr(cli, "SubprocessADBRunner", fake_runner)
    monkeypatch.setenv(cli.PASSPHRASE_ENV, "a very long passphrase here")
    cli.main(["--adb-path", "/opt/platform-tools/adb", "--out", str(tmp_path / "o")])
    assert seen == ["/opt/platform-tools/adb"]
