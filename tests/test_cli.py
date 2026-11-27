from __future__ import annotations

from pathlib import Path

import pytest

from fakes import ScriptedUI
from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest import cli


def test_no_secret_flags_on_command_line() -> None:
    helptext = cli.build_parser().format_help().lower()
    for flag in ("--key", "--passphrase", "--password"):
        assert flag not in helptext
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--key", "ab" * 32])


def test_cli_offline_bundle_success(
    tmp_path: Path,
    mock: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / "msgstore.db").write_bytes(mock["msgstore_plain"].read_bytes())
    monkeypatch.setenv(cli.PASSPHRASE_ENV, "a very long passphrase here")
    monkeypatch.setattr(
        "waarchive.ingest.pipeline.KdfParams.fresh",
        lambda **_: __import__("waarchive.keys", fromlist=["KdfParams"]).KdfParams(
            b"s" * 16, 1, 8, 1
        ),
    )
    rc = cli.main(["--bundle", str(bundle), "--out", str(tmp_path / "out")], ui=ScriptedUI())
    assert rc == 0 and (tmp_path / "out" / "archive.db").exists()


def test_cli_prompted_passphrase_mismatch_and_weak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(cli.PASSPHRASE_ENV, raising=False)
    assert (
        cli.main(
            ["--bundle", str(tmp_path), "--out", str(tmp_path / "o")],
            ui=ScriptedUI(secrets=["abcdefghijklmn", "different-different"]),
        )
        == 2
    )
    assert (
        cli.main(
            ["--bundle", str(tmp_path), "--out", str(tmp_path / "o")],
            ui=ScriptedUI(secrets=["short", "short"]),
        )
        == 2
    )


def test_cli_missing_adb_gives_clean_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.PASSPHRASE_ENV, "a very long passphrase here")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli.main(["--out", str(tmp_path / "o")], ui=ScriptedUI()) == 2


def test_cli_bad_bundle_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cli.PASSPHRASE_ENV, "a very long passphrase here")
    assert (
        cli.main(
            ["--bundle", str(tmp_path / "missing"), "--out", str(tmp_path / "o")], ui=ScriptedUI()
        )
        == 2
    )
    assert gen.CANARY  # fixture module importable
