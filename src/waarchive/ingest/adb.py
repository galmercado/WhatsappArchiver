"""ADB abstraction. Nothing here ever invokes a shell on the host (no shell=True)."""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 - argv-list only, see SubprocessADBRunner
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..secure_fs import open_private

SERIAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{3,63}$")
REMOTE_PATH_RE = re.compile(r"^/[A-Za-z0-9._/\-]{1,512}$")
ALLOWED_REMOTE_PREFIXES = ("/sdcard/", "/data/data/")


class ADBError(Exception):
    pass


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


class ADBRunner(Protocol):
    """Everything the pipeline needs from adb. Fake this in tests."""

    def run(self, args: Sequence[str], *, timeout: float = 30.0) -> RunResult: ...

    def run_to_file(self, args: Sequence[str], dest: Path, *, timeout: float = 600.0) -> int: ...


def validate_serial(serial: str) -> str:
    if not SERIAL_RE.fullmatch(serial):
        raise ADBError("invalid device serial")
    return serial


def validate_remote_path(path: str) -> str:
    if (
        not REMOTE_PATH_RE.fullmatch(path)
        or ".." in path.split("/")
        or "//" in path
        or not path.startswith(ALLOWED_REMOTE_PREFIXES)
    ):
        raise ADBError("remote path not permitted")
    return path


class SubprocessADBRunner:
    """Real adb. Arguments are always passed as a list; the host shell is never involved."""

    def __init__(self, adb_path: str | None = None) -> None:
        resolved = adb_path or shutil.which("adb")
        if not resolved:
            raise ADBError("adb not found on PATH (install Android platform-tools)")
        self._adb = resolved

    def run(self, args: Sequence[str], *, timeout: float = 30.0) -> RunResult:
        try:
            proc = subprocess.run(  # noqa: S603  # nosec B603 - fixed binary, validated argv list
                [self._adb, *args], capture_output=True, timeout=timeout, check=False, shell=False
            )
        except subprocess.TimeoutExpired as exc:
            raise ADBError("adb command timed out") from exc
        except OSError as exc:
            raise ADBError("could not execute adb") from exc
        return RunResult(proc.returncode, proc.stdout, proc.stderr)

    def run_to_file(self, args: Sequence[str], dest: Path, *, timeout: float = 600.0) -> int:
        try:
            with open_private(dest) as fh:
                proc = subprocess.run(  # noqa: S603  # nosec B603 - fixed binary, validated argv list
                    [self._adb, *args],
                    stdout=fh,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                    check=False,
                    shell=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise ADBError("adb command timed out") from exc
        except OSError as exc:
            raise ADBError("could not execute adb") from exc
        return proc.returncode
