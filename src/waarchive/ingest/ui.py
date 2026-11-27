"""User interaction abstraction (terminal in production, scripted in tests)."""

from __future__ import annotations

import getpass
import shutil
import sys
import threading
import time
from typing import Protocol

from .progress import render_bar

UNROOTED_ALERT = """\
==============================================================================
  !!  DEVICE IS NOT ROOTED  !!
==============================================================================
  Android's app sandbox blocks access to WhatsApp's private data
  (/data/data/com.whatsapp/). Automated extraction of the private key and
  databases is therefore NOT possible on this device.

  This tool will NOT attempt exploits or any root/bootloader tricks.
  WARNING: unlocking a Samsung bootloader triggers a FACTORY WIPE (and trips
  Knox permanently). Do not do that to get at your chats.

  What happens next:
    * Whatever is readable on shared storage (msgstore.db.crypt14/15 and the
      Media/ folder) is pulled now.
    * To decrypt it you need ONE of:
        1) your 64-digit End-to-End Encrypted Backup key
           (WhatsApp > Settings > Chats > Chat backup > End-to-end encrypted
            backup > Turn on > "Use 64-digit encryption key instead"), or
        2) a local folder with a manually exported `key` and/or
           `msgstore.db` / `wa.db`.
==============================================================================
"""


class UI(Protocol):
    def say(self, msg: str) -> None: ...
    def alert(self, msg: str) -> None: ...
    def ask(self, prompt: str) -> str: ...
    def ask_secret(self, prompt: str) -> bytearray: ...
    def progress(self, label: str, done: int, total: int | None, unit: str = "bytes") -> None: ...
    def progress_end(self) -> None: ...


class TerminalUI:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._label: str | None = None
        self._t0 = 0.0
        self._last = 0.0
        self._last_pct = -1
        self._tty = sys.stdout.isatty()

    def progress(self, label: str, done: int, total: int | None, unit: str = "bytes") -> None:
        with self._lock:
            now = time.monotonic()
            if label != self._label:
                if self._tty and self._label is not None:
                    print()  # keep the previous bar's final state on screen
                self._label, self._t0, self._last, self._last_pct = label, now, 0.0, -1
            finished = total is not None and done >= total
            if self._tty:
                if now - self._last < 0.1 and not finished:
                    return
                self._last = now
                line = render_bar(label, done, total, unit=unit, elapsed=now - self._t0)
                width = shutil.get_terminal_size((100, 20)).columns - 1
                print("\r" + line[:width].ljust(width), end="", flush=True)
            else:  # logs / pipes: a line every 10 %
                pct = int(done * 100 / total) // 10 * 10 if total else -1
                if pct != self._last_pct and total:
                    self._last_pct = pct
                    print(
                        render_bar(label, done, total, unit=unit, elapsed=now - self._t0),
                        flush=True,
                    )

    def progress_end(self) -> None:
        with self._lock:
            if self._tty and self._label is not None:
                print()
            self._label = None

    def _break_bar(self) -> None:
        if self._tty and self._label is not None:
            print()
            self._label = None

    def say(self, msg: str) -> None:
        with self._lock:
            self._break_bar()
            print(msg)

    def alert(self, msg: str) -> None:
        with self._lock:
            self._break_bar()
            print(msg, file=sys.stderr)

    def ask(self, prompt: str) -> str:
        return input(prompt)

    def ask_secret(self, prompt: str) -> bytearray:
        return bytearray(getpass.getpass(prompt).encode("utf-8"))
