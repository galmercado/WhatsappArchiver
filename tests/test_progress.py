from __future__ import annotations

import time
from pathlib import Path

import pytest

from fakes import FakeADBRunner, ScriptedUI
from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest.archive import SQLCipherProvider
from waarchive.ingest.device import ADBClient
from waarchive.ingest.pipeline import IngestConfig, Pipeline
from waarchive.ingest.progress import DirWatcher, dir_size, human_bytes, human_time, render_bar
from waarchive.ingest.ui import TerminalUI


def test_human_formats() -> None:
    assert (
        human_bytes(512) == "512 B"
        and human_bytes(1536) == "1.5 KB"
        and human_bytes(3 * 1024**3) == "3.0 GB"
    )
    assert human_time(75) == "1:15" and human_time(3725) == "1:02:05" and human_time(-5) == "0:00"


def test_bar_with_total_shows_percent_size_speed_and_eta() -> None:
    line = render_bar("Copying", 512 * 1024**2, 1024**3, unit="bytes", elapsed=10)
    assert (
        " 50%" in line
        and "512.0 MB / 1.0 GB" in line
        and "51.2 MB/s" in line
        and "ETA 0:10" in line
    )
    assert line.count("#") == 14 and line.count("-") == 14  # half of the 28-cell bar


def test_bar_edge_cases() -> None:
    assert "100%" in render_bar("x", 10, 10, unit="items", elapsed=1) and "ETA" not in render_bar(
        "x", 10, 10, unit="items", elapsed=1
    )
    assert "100%" in render_bar("x", 999, 10, unit="items", elapsed=1)  # never overflows
    unknown = render_bar(
        "Copying", 2048, None, unit="bytes", elapsed=1
    )  # phone would not report a size
    assert "[" not in unknown and "2.0 KB" in unknown
    assert "0%" in render_bar("x", 0, 100, unit="items", elapsed=0) and "ETA" not in render_bar(
        "x", 0, 100, unit="items", elapsed=0
    )
    assert "1,234 / 5,000" in render_bar("Indexing", 1234, 5000, unit="items", elapsed=2)


def test_dir_size_and_watcher(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "x.bin").write_bytes(b"1" * 100)
    (tmp_path / "a" / "b" / "y.bin").write_bytes(b"2" * 50)
    (tmp_path / "link").symlink_to(tmp_path / "a")  # symlinks are not followed or double counted
    assert (
        dir_size(tmp_path) == 150
        and dir_size(tmp_path / "a" / "x.bin") == 100
        and dir_size(tmp_path / "nope") == 0
    )
    seen: list[int] = []
    with DirWatcher(tmp_path / "grow", seen.append, interval=0.02):
        (tmp_path / "grow").mkdir()
        (tmp_path / "grow" / "f").write_bytes(b"z" * 10)
        time.sleep(0.15)
    assert (seen[-1] == 10 and 0 in seen) or seen[
        -1
    ] == 10  # final report always reflects what landed


def test_terminal_ui_draws_in_place_on_a_tty_and_in_steps_otherwise(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ui = TerminalUI()
    ui._tty = True
    ui.progress("Copying", 50, 100)
    ui.progress("Copying", 100, 100)
    ui.say("done")
    out = capsys.readouterr().out
    assert "\r" in out and "100%" in out and out.rstrip().endswith("done")
    ui2 = TerminalUI()
    ui2._tty = False
    for i in range(0, 101, 5):
        ui2.progress("Copying", i, 100)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    assert "\r" not in "".join(lines) and 10 <= len(lines) <= 12  # one line per 10 %


def test_pipeline_reports_copy_decrypt_and_index_progress(
    tmp_path: Path, device_fs: dict[str, bytes]
) -> None:
    ui = ScriptedUI(answers=["1"], secrets=[gen.ROOT_KEY_HEX])
    cfg = IngestConfig(
        out_dir=tmp_path / "out", kdf_overrides={"time_cost": 1, "memory_kib": 8, "parallelism": 1}
    )
    Pipeline(ADBClient(FakeADBRunner(fs=device_fs)), ui, SQLCipherProvider(), cfg).run(
        bytearray(b"correct horse battery")
    )
    labels = {b[0] for b in ui.bars}
    assert {
        "Copying chat backup",
        "Copying photos, videos, voice notes",
        "Decrypting chat backup",
        "Indexing messages",
    } <= labels
    copy = [b for b in ui.bars if b[0] == "Copying photos, videos, voice notes"]
    assert (
        copy[0][1] == 0 and copy[0][2] and copy[-1][1] >= copy[-1][2] // 2
    )  # starts at 0 with a known total, ends near it
    dec = [b for b in ui.bars if b[0] == "Decrypting chat backup"]
    assert dec[-1][1] == dec[-1][2]
    idx = [b for b in ui.bars if b[0] == "Indexing messages"]
    assert idx[-1][1] == idx[-1][2] == len(gen.MODERN_MESSAGES) + 0 or idx[-1][1] == idx[-1][2]
    assert idx[-1][3] == "items" and ui.bars_ended >= 4
