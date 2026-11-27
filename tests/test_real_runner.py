"""SubprocessADBRunner against a stand-in `adb` executable: argv is passed verbatim, no shell."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from waarchive.ingest.adb import ADBError, SubprocessADBRunner


@pytest.fixture
def fake_adb(tmp_path: Path) -> Path:
    script = tmp_path / "adb"
    script.write_text('#!/bin/sh\nfor a in "$@"; do printf "[%s]\\n" "$a"; done\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_args_passed_verbatim_without_shell_expansion(fake_adb: Path, tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    nasty = f"x; touch {marker}; $(touch {marker}) `touch {marker}`"
    res = SubprocessADBRunner(str(fake_adb)).run(["shell", nasty])
    assert f"[{nasty}]".encode() in res.stdout
    assert not marker.exists()


def test_run_to_file_is_private(fake_adb: Path, tmp_path: Path) -> None:
    dest = tmp_path / "out.bin"
    assert SubprocessADBRunner(str(fake_adb)).run_to_file(["pull", "a"], dest) == 0
    assert dest.read_bytes() == b"[pull]\n[a]\n" and (dest.stat().st_mode & 0o777) == 0o600


def test_missing_adb_and_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(ADBError, match="not found"):
        SubprocessADBRunner()
    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nexec /bin/sleep 5\n")
    slow.chmod(0o755)
    with pytest.raises(ADBError, match="timed out"):
        SubprocessADBRunner(str(slow)).run(["x"], timeout=0.3)
