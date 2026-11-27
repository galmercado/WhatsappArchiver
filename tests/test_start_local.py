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


def test_qr_matrix_has_finder_patterns_and_renders_on_any_terminal_theme() -> None:
    from waarchive import qr

    uri = "otpauth://totp/archive?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=WhatsApp+Archive"
    m = qr.matrix(uri)
    n = len(m)
    assert n >= 21 and all(len(r) == n for r in m)
    for r, c in ((0, 0), (0, n - 7), (n - 7, 0)):  # three 7x7 finder squares: solid dark outer ring
        assert all(
            m[r][c + i] and m[r + 6][c + i] and m[r + i][c] and m[r + i][c + 6] for i in range(7)
        )
    ansi = qr.render_ansi(m)
    lines = ansi.split("\n")
    assert len(lines) == n + 2 * qr.QUIET
    assert (
        "\x1b[40m" in ansi and "\x1b[47m" in ansi
    )  # explicit black/white: independent of the terminal theme
    assert all(
        line.count("\x1b[0m") == n + 2 * qr.QUIET for line in lines
    )  # one cell per module incl. quiet zone
    assert qr.render_plain(m).count("##") == sum(map(sum, m))


def test_qr_svg_is_private_and_setup_shows_key_and_removes_svg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("builtins.input", lambda _="": "")
    out: list[str] = []
    answers = iter(["a-long-enough-password", "a-long-enough-password"])
    _h, secret = start_local.ensure_auth(tmp_path / "auth", lambda _p: next(answers), out.append)
    text = "\n".join(out)
    assert "Scan a QR code" in text and secret in text and "authenticator-qr.svg" in text
    assert not (
        tmp_path / "auth" / "authenticator-qr.svg"
    ).exists()  # deleted once setup is confirmed
    from waarchive import qr

    qr.write_svg("otpauth://totp/x?secret=ABC", tmp_path / "q.svg")
    assert (tmp_path / "q.svg").read_text().lstrip().startswith("<?xml") or "<svg" in (
        tmp_path / "q.svg"
    ).read_text()
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "q.svg").stat().st_mode) == 0o600


@pytest.mark.parametrize("style", ["ansi", "plain"])
def test_rendered_qr_decodes_back_to_the_setup_uri(style: str) -> None:
    """Independent check: parse our own terminal output back into pixels and read it with a QR decoder."""
    import re

    zxingcpp = pytest.importorskip("zxingcpp")
    np = pytest.importorskip("numpy")
    from waarchive import qr

    uri = "otpauth://totp/archive?secret=JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP&issuer=WhatsApp+Archive"
    text = qr.render_ansi(qr.matrix(uri)) if style == "ansi" else qr.render_plain(qr.matrix(uri))
    rows = []
    for line in text.split("\n"):
        if style == "ansi":
            rows.append(
                [0 if c == "40" else 255 for c in re.findall(r"\x1b\[(40|47)m  \x1b\[0m", line)]
            )
        else:
            rows.append([0 if line[i : i + 2] == "##" else 255 for i in range(0, len(line), 2)])
    img = np.kron(np.array(rows, dtype=np.uint8), np.ones((8, 8), dtype=np.uint8))
    assert [r.text for r in zxingcpp.read_barcodes(img)] == [uri]
