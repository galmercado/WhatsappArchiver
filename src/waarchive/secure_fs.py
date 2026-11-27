"""Private temp storage, best-effort secure wipe and zeroization helpers."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

_WIPE_CHUNK = 1 << 20


def open_private(path: Path) -> BinaryIO:
    """Create/truncate *path* with mode 0600 (never world/group readable)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "wb")


def zeroize(buf: bytearray | None) -> None:
    """Overwrite a bytearray in place (best effort; Python may hold other copies)."""
    if buf is not None:
        for i in range(len(buf)):
            buf[i] = 0


def wipe_file(path: Path) -> None:
    """Overwrite with zeros, fsync, unlink. Best effort on flash/CoW filesystems."""
    try:
        if path.is_symlink() or not path.is_file():
            path.unlink(missing_ok=True)
            return
        size = path.stat().st_size
        with path.open("r+b") as fh:
            remaining = size
            zeros = bytes(min(_WIPE_CHUNK, max(size, 1)))
            while remaining > 0:
                n = min(len(zeros), remaining)
                fh.write(zeros[:n])
                remaining -= n
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass
    finally:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


def wipe_tree(root: Path) -> None:
    if not root.exists():
        return
    for dirpath, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            wipe_file(Path(dirpath) / name)
    shutil.rmtree(root, ignore_errors=True)


@contextlib.contextmanager
def secure_tempdir(prefix: str = "waarchive-", base: Path | None = None) -> Iterator[Path]:
    """0700 temp dir that is wiped on exit, including on exceptions."""
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=str(base) if base else None))
    os.chmod(path, 0o700)
    try:
        yield path
    finally:
        wipe_tree(path)
