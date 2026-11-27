"""Command-line entry point. Secrets are accepted only via prompt or environment variables,
never argv (argv is visible to other local users via the process list)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from ..keys import KeyError_, check_passphrase
from ..logsafe import configure_logging
from ..secure_fs import zeroize
from .adb import ADBError, SubprocessADBRunner
from .archive import SQLCipherProvider
from .device import ADBClient
from .pipeline import IngestConfig, IngestError, Pipeline
from .ui import UI, TerminalUI

PASSPHRASE_ENV = "WA_ARCHIVE_PASSPHRASE"  # noqa: S105  # nosec B105 - env var name, not a secret


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="extract_and_ingest.py",
        description="Extract, decrypt and normalize a WhatsApp archive from a connected Android device.",
        epilog=f"Secrets: archive passphrase via prompt or ${PASSPHRASE_ENV}; "
        "the 64-digit backup key is prompted for (hidden).",
    )
    p.add_argument(
        "--out", type=Path, default=Path("archive"), help="output directory (default: ./archive)"
    )
    p.add_argument("--serial", help="ADB device serial (required if several are attached)")
    p.add_argument(
        "--package", default="com.whatsapp", help="WhatsApp package (com.whatsapp.w4b for Business)"
    )
    p.add_argument(
        "--adb-path",
        type=Path,
        help="full path to the adb program (only needed if it is not on your PATH)",
    )
    p.add_argument(
        "--vcf",
        type=Path,
        help="contacts export (.vcf) with names and photos (Contacts app > Export)",
    )
    p.add_argument(
        "--avatars",
        type=Path,
        help="folder of profile pictures named by phone number, e.g. 972501234567.jpg",
    )
    p.add_argument(
        "--no-phonebook",
        action="store_true",
        help="do not read names/photos from the phone's address book",
    )
    p.add_argument(
        "--bundle", type=Path, help="skip ADB: folder with key / msgstore.db / wa.db (offline mode)"
    )
    p.add_argument("--verbose", action="store_true", help="debug logging (still PII-scrubbed)")
    return p


def _get_passphrase(ui: UI) -> bytearray:
    env = os.environ.get(PASSPHRASE_ENV)
    if env:
        return bytearray(env.encode("utf-8"))
    first = ui.ask_secret("New archive passphrase (min 12 chars, input hidden): ")
    second = ui.ask_secret("Repeat passphrase: ")
    try:
        if first != second:
            raise KeyError_("passphrases do not match")
        return bytearray(first)
    finally:
        zeroize(first)
        zeroize(second)


def main(argv: Sequence[str] | None = None, *, ui: UI | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    log = logging.getLogger("waarchive")
    ui = ui or TerminalUI()
    passphrase: bytearray | None = None
    try:
        passphrase = _get_passphrase(ui)
        check_passphrase(passphrase)
        adb_exe = str(args.adb_path) if args.adb_path else None
        adb = None if args.bundle else ADBClient(SubprocessADBRunner(adb_exe))
        cfg = IngestConfig(
            out_dir=args.out,
            package=args.package,
            serial=args.serial,
            bundle=args.bundle,
            vcf=args.vcf,
            avatars=args.avatars,
            use_phonebook=not args.no_phonebook,
        )
        result = Pipeline(adb, ui, SQLCipherProvider(), cfg).run(passphrase)
    except IngestError as exc:
        log.error("%s", exc)
        return exc.exit_code
    except (KeyError_, ADBError) as exc:
        log.error("%s", exc)
        return 2
    except Exception:  # last resort: generic message, scrubbed traceback only with --verbose
        log.error("unexpected failure", exc_info=args.verbose)
        return 5
    finally:
        zeroize(passphrase)
    ui.say(
        f"Done: {result.stats.chats} chats, {result.stats.messages} messages, "
        f"{result.stats.media_stored} media files, {result.stats.names_added} contact names, "
        f"{result.stats.pictures_added} pictures. Archive: {result.archive}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
