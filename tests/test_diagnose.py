from __future__ import annotations

from pathlib import Path

import pytest

from fakes import FakeADBRunner, ScriptedUI
from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest import diagnose

KEY = gen.ROOT_KEY_HEX


def run(files: list[Path], key: str = KEY) -> tuple[int, ScriptedUI]:
    ui = ScriptedUI(secrets=[key])
    argv = [a for f in files for a in ("--file", str(f))]
    return diagnose.main([*argv, "--watchdog", "5"], ui=ui), ui


def text(ui: ScriptedUI) -> str:
    return "\n".join(ui.said)


def test_good_backups_report_each_stage_and_database_shape(mock: dict[str, Path]) -> None:
    code, ui = run([mock["msgstore_crypt"], mock["wa_crypt"]])
    out = text(ui)
    assert code == 0 and "All backups decrypt fine" in out
    assert (
        "header OK: IV found (16 bytes)" in out
        and "DECRYPTED, authenticated and valid SQLite" in out
    )
    assert "wa_contacts=3" in out and "message=21" in out  # table names and counts only
    assert "layout with 16-byte trailer: DECRYPTED" in out


def test_md5_trailer_layout_is_found_and_the_other_layout_is_reported_as_failing(
    tmp_path: Path, mock: dict[str, Path]
) -> None:
    f = tmp_path / "msgstore.db.crypt15"
    f.write_bytes(gen.encrypt_backup(mock["msgstore_plain"].read_bytes(), 15, md5_trailer=True))
    code, ui = run([f])
    out = text(ui)
    assert (
        code == 0
        and "16-byte trailer: no (authentication failed" in out
        and "32-byte trailer: DECRYPTED" in out
    )


def test_wrong_key_is_diagnosed_without_a_traceback_or_hang(mock: dict[str, Path]) -> None:
    code, ui = run([mock["wa_crypt"]], key="ab" * 32)
    out = text(ui)
    assert code == 1 and out.count("authentication failed") + out.count("bad key or layout") >= 2
    assert "RESULT: could not decrypt" in out and "Traceback" not in out


def test_unknown_header_and_wrong_extension_and_truncation(
    tmp_path: Path, mock: dict[str, Path]
) -> None:
    junk = tmp_path / "x.db.crypt15"
    junk.write_bytes(b"\x00\x01" + b"\x07" * 50)
    trunc = tmp_path / "t.db.crypt15"
    trunc.write_bytes(mock["wa_crypt"].read_bytes()[:40])
    other = tmp_path / "notes.txt"
    other.write_text("hi")
    code, ui = run([junk, trunc, other])
    out = text(ui)
    assert code == 1 and "HEADER NOT UNDERSTOOD" in out and "not a .crypt14/.crypt15 file" in out


def test_the_key_never_appears_in_the_output_and_bad_keys_are_refused(
    mock: dict[str, Path],
) -> None:
    _, ui = run([mock["msgstore_crypt"]])
    blob = text(ui) + "".join(ui.alerts)
    assert KEY not in blob and gen.ROOT_KEY.hex().upper() not in blob.upper()
    code, ui2 = run([mock["msgstore_crypt"]], key="not a key")
    assert code == 2 and "not a valid key" in text(ui2)


def test_phone_mode_copies_only_the_two_backup_files_not_the_media(
    mock: dict[str, Path], device_fs: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = FakeADBRunner(fs=device_fs)
    monkeypatch.setattr(diagnose, "SubprocessADBRunner", lambda _p=None: runner)
    ui = ScriptedUI(secrets=[KEY])
    assert diagnose.main(["--watchdog", "5"], ui=ui) == 0
    pulls = [a for a in runner.log if "pull" in a]
    assert len(pulls) == 2 and all("crypt15" in " ".join(p) for p in pulls)
    assert not any("/Media" in " ".join(p) for p in pulls)


def test_phone_mode_without_a_phone_or_backups_is_friendly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(diagnose, "SubprocessADBRunner", lambda _p=None: FakeADBRunner(devices=[]))
    ui = ScriptedUI(secrets=[KEY])
    assert diagnose.main([], ui=ui) == 3 and "Phone not available" in text(ui)
    monkeypatch.setattr(diagnose, "SubprocessADBRunner", lambda _p=None: FakeADBRunner(fs={}))
    ui2 = ScriptedUI(secrets=[KEY])
    assert diagnose.main([], ui=ui2) == 3 and "No WhatsApp backup folder" in text(ui2)


def test_the_watchdog_prints_the_stuck_line_when_a_stage_is_slow(
    tmp_path: Path,
    mock: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    import time

    real = diagnose._stream_decrypt

    def slow(*a, **k):  # type: ignore[no-untyped-def]
        time.sleep(2.2)  # pretend this is the step that never returns
        return real(*a, **k)

    monkeypatch.setattr(diagnose, "_stream_decrypt", slow)
    ui = ScriptedUI(secrets=[KEY])
    assert diagnose.main(["--file", str(mock["wa_crypt"]), "--watchdog", "1"], ui=ui) == 0
    err = capfd.readouterr().err
    assert "most recent call first" in err and "in slow" in err  # the dump names the stuck function


def test_stack_after_option_exists() -> None:
    from waarchive.ingest import cli

    assert "--stack-after" in cli.build_parser().format_help()
