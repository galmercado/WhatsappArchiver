"""`diagnose_backup.py`: find out why a WhatsApp backup file will not decrypt, step by step.

Copies only the two small backup files (not the photos), then runs every decryption stage separately with timings
and a watchdog that prints where the program is if a stage takes too long. Prints structure and counts only:
never message text, names or numbers, and never your key.
"""

from __future__ import annotations

import argparse
import faulthandler
import re
import sqlite3
import sys
import time
import zlib
from collections.abc import Callable, Sequence
from pathlib import Path

from cryptography.exceptions import InvalidTag

from ..logsafe import configure_logging
from ..secure_fs import secure_tempdir, zeroize
from .adb import ADBError, SubprocessADBRunner
from .crypt import (
    MAX_HEADER,
    SQLITE_MAGIC,
    DecryptError,
    _stream_decrypt,
    derive_crypt15_key,
    key_candidates_from_file,
    parse_header,
    parse_hex_key,
)
from .device import ADBClient, DeviceError
from .progress import human_bytes
from .ui import UI, TerminalUI

DEFAULT_WATCHDOG_S = 20


def _stage(say: Callable[[str], None], text: str) -> None:
    say(f"  - {text}")


def describe_header(data: bytes, say: Callable[[str], None]) -> tuple[bytes, int] | None:
    first = data[:2]
    _stage(
        say,
        f"first bytes: header length={first[0] if first else '?'}, flag={first[1] if len(first) > 1 else '?'}",
    )
    try:
        iv, payload = parse_header(data[: MAX_HEADER + 2])
    except DecryptError as exc:
        _stage(
            say,
            f"HEADER NOT UNDERSTOOD ({exc}). This file is in a format the tool does not read yet.",
        )
        return None
    _stage(say, f"header OK: IV found ({len(iv)} bytes), encrypted data starts at byte {payload}")
    return iv, payload


def try_variant(
    src: Path,
    dest: Path,
    aes_key: bytes,
    iv: bytes,
    payload: int,
    trailer: int,
    say: Callable[[str], None],
    watchdog_s: int,
) -> bool:
    size = src.stat().st_size
    end = size - trailer
    if end <= payload:
        _stage(say, f"layout with {trailer}-byte trailer: file too short")
        return False
    with src.open("rb") as fh:
        fh.seek(end)
        tag = fh.read(16)
    t0 = time.monotonic()
    faulthandler.dump_traceback_later(
        watchdog_s, repeat=True, file=sys.stderr
    )  # prints the stuck line, keeps running
    try:
        _stream_decrypt(src, dest, aes_key, iv, tag, payload, end, 32 * 1024**3)
        _stage(
            say,
            f"layout with {trailer}-byte trailer: DECRYPTED, authenticated and valid SQLite ({time.monotonic() - t0:.1f}s)",
        )
        return True
    except InvalidTag:
        why = "authentication failed (wrong key, or this is not the right trailer layout)"
    except zlib.error as exc:
        why = f"authenticated data is not valid zlib ({exc})"
    except DecryptError as exc:
        why = str(exc)
    finally:
        faulthandler.cancel_dump_traceback_later()
    dest.unlink(missing_ok=True)
    _stage(say, f"layout with {trailer}-byte trailer: no ({why}) [{time.monotonic() - t0:.1f}s]")
    return False


def describe_sqlite(path: Path, say: Callable[[str], None]) -> None:
    """Table names and row counts only."""
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        tables = [
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        ]
        shown = []
        for t in tables[:60]:
            if re.fullmatch(r"[A-Za-z0-9_]+", t):
                n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # noqa: S608  # nosec B608 - validated identifier
                shown.append(f"{t}={n}")
        con.close()
        _stage(say, f"database has {len(tables)} tables: " + ", ".join(shown))
    except sqlite3.Error as exc:
        _stage(say, f"decrypted file is not a readable SQLite database ({type(exc).__name__})")


def analyze(
    src: Path,
    keys: list[bytearray],
    tmp: Path,
    say: Callable[[str], None],
    watchdog_s: int = DEFAULT_WATCHDOG_S,
) -> bool:
    m = re.search(r"\.crypt(14|15)$", src.name)
    say(f"\n== {re.sub(r'^pulled_', '', src.name)}  ({human_bytes(src.stat().st_size)})")
    if not m:
        _stage(say, "not a .crypt14/.crypt15 file")
        return False
    kind = int(m.group(1))
    with src.open("rb") as fh:
        parsed = describe_header(fh.read(MAX_HEADER + 2), say)
    if parsed is None:
        return False
    iv, payload = parsed
    for i, root in enumerate(keys, 1):
        aes = derive_crypt15_key(root) if kind == 15 else bytes(root)
        for trailer in (16, 32):
            out = tmp / f"diag_{src.stem}_{i}_{trailer}.db"
            if try_variant(src, out, aes, iv, payload, trailer, say, watchdog_s):
                describe_sqlite(out, say)
                out.unlink(missing_ok=True)
                return True
    _stage(
        say,
        "RESULT: could not decrypt. If you are sure the 64 digits are right, send me everything above.",
    )
    return False


def _pull_backups(
    adb: ADBClient, serial: str, package: str, tmp: Path, say: Callable[[str], None]
) -> list[Path]:
    layout = adb.discover_storage(serial, package)
    if layout is None:
        say("No WhatsApp backup folder found on the phone.")
        return []
    got: list[Path] = []
    for remote in layout.msgstore_backups[:1] + layout.wa_backups[:1]:
        dest = tmp / ("pulled_" + remote.rsplit("/", 1)[-1])
        say(f"Copying {remote.rsplit('/', 1)[-1]} ...")
        if adb.pull(serial, remote, dest) and dest.exists():
            got.append(dest)
    return got


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="diagnose_backup.py", description=__doc__)
    p.add_argument(
        "--file",
        type=Path,
        action="append",
        help="check a backup file on this computer instead of using the phone",
    )
    p.add_argument("--serial")
    p.add_argument("--package", default="com.whatsapp")
    p.add_argument("--adb-path", type=Path)
    p.add_argument(
        "--watchdog",
        type=int,
        default=DEFAULT_WATCHDOG_S,
        help="seconds before a slow step prints where it is",
    )
    return p


def main(argv: Sequence[str] | None = None, *, ui: UI | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(False)
    ui = ui or TerminalUI()
    raw = ui.ask_secret("64-digit end-to-end encrypted backup key (input hidden): ")
    try:
        keys = [parse_hex_key(raw.decode("utf-8", "replace"))]
    except DecryptError as exc:
        ui.say(f"That is not a valid key: {exc}")
        return 2
    finally:
        zeroize(raw)
    ok = False
    try:
        with secure_tempdir(prefix="waarchive-diag-") as tmp:
            files: list[Path] = list(args.file or [])
            if not files:
                try:
                    adb = ADBClient(
                        SubprocessADBRunner(str(args.adb_path) if args.adb_path else None)
                    )
                    serial = adb.require_device(args.serial).serial
                except (ADBError, DeviceError) as exc:
                    ui.say(f"Phone not available: {exc}")
                    return 3
                files = _pull_backups(adb, serial, args.package, tmp, ui.say)
            if not files:
                return 3
            results = [analyze(f, keys, tmp, ui.say, args.watchdog) for f in files]
            ok = all(results)
    finally:
        for k in keys:
            zeroize(k)
    ui.say(
        "\nAll backups decrypt fine."
        if ok
        else "\nSome backups did not decrypt: please send me the lines above (they contain no chat content or key)."
    )
    return 0 if ok else 1


__all__ = ["SQLITE_MAGIC", "analyze", "key_candidates_from_file", "main"]
