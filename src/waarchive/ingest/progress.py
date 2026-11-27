"""Terminal progress bars (pure rendering + a thread that watches a growing directory)."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

BAR_WIDTH = 28


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(seconds: float) -> str:
    s = int(max(seconds, 0))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def render_bar(
    label: str, done: int, total: int | None, *, unit: str, elapsed: float, width: int = BAR_WIDTH
) -> str:
    """One line such as: ``Copying photos [#########-----------]  52%  1.2 GB / 2.3 GB  14.0 MB/s  ETA 1:20``."""
    fmt = human_bytes if unit == "bytes" else (lambda v: f"{int(v):,}")
    rate = done / elapsed if elapsed > 0 else 0.0
    if total is None or total <= 0:
        spinner = "|/-\\"[int(elapsed * 4) % 4]
        speed = f"  {human_bytes(rate)}/s" if unit == "bytes" and rate else ""
        return f"{label} {spinner} {fmt(done)}{speed}"
    frac = min(max(done / total, 0.0), 1.0)
    filled = int(frac * width)
    bar = "#" * filled + "-" * (width - filled)
    eta = f"  ETA {human_time((total - done) / rate)}" if rate > 0 and done < total else ""
    speed = f"  {human_bytes(rate)}/s" if unit == "bytes" and rate else ""
    return f"{label} [{bar}] {frac * 100:3.0f}%  {fmt(done)} / {fmt(total)}{speed}{eta}"


def dir_size(path: Path) -> int:
    """Total size of regular files below *path* (symlinks ignored); 0 if it does not exist yet."""
    if path.is_file() and not path.is_symlink():
        return path.stat().st_size
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        stack.append(Path(e.path))
                    elif e.is_file(follow_symlinks=False):
                        total += e.stat(follow_symlinks=False).st_size
        except OSError:
            continue
    return total


class DirWatcher:
    """While a blocking copy runs, report how many bytes have landed in *path* every *interval* seconds."""

    def __init__(self, path: Path, report: Callable[[int], None], interval: float = 0.5) -> None:
        self._path, self._report, self._interval = path, report, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._report(dir_size(self._path))

    def __enter__(self) -> DirWatcher:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self._report(dir_size(self._path))
