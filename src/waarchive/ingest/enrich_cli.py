"""`enrich_contacts.py`: add contact names and pictures to an EXISTING archive (no need to copy the phone again)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from ..keys import KeyError_, derive_master, read_params, subkey
from ..logsafe import configure_logging
from ..media_vault import MediaVault
from ..secure_fs import zeroize
from .adb import ADBError, SubprocessADBRunner
from .archive import SQLCipherProvider, WrongKeyError
from .cli import PASSPHRASE_ENV
from .contacts import collect_phonebook, enrich_archive
from .device import ADBClient, DeviceError
from .ui import UI, TerminalUI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="enrich_contacts.py",
        description="Add contact names and profile pictures to an existing archive, using your phone's address book, "
        "a contacts export (.vcf) and/or a folder of pictures.",
    )
    p.add_argument(
        "--archive", type=Path, default=Path("archive"), help="archive folder (default: ./archive)"
    )
    p.add_argument("--serial", help="ADB device serial (if several devices are attached)")
    p.add_argument("--adb-path", type=Path, help="full path to the adb program")
    p.add_argument("--vcf", type=Path, help="contacts export (.vcf) with names and photos")
    p.add_argument(
        "--avatars",
        type=Path,
        help="folder of pictures named by phone number, e.g. 972501234567.jpg",
    )
    p.add_argument(
        "--no-phonebook", action="store_true", help="do not read the phone's address book"
    )
    p.add_argument("--verbose", action="store_true")
    return p


def main(argv: Sequence[str] | None = None, *, ui: UI | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    log = logging.getLogger("waarchive")
    ui = ui or TerminalUI()
    arch: Path = args.archive
    if not (arch / "archive.db").is_file() or not (arch / "archive.kdf.json").is_file():
        ui.say(f"No archive found in '{arch}'. Run extract_and_ingest.py first.")
        return 2

    env_pass = os.environ.get(PASSPHRASE_ENV)
    passphrase = (
        bytearray(env_pass.encode())
        if env_pass
        else ui.ask_secret("Vault passphrase of this archive (input hidden): ")
    )
    master: bytearray | None = None
    db = None
    try:
        master = derive_master(passphrase, read_params(arch / "archive.kdf.json"))
        vault = MediaVault(arch / "media", subkey(master, "media"), subkey(master, "media-name"))
        db = SQLCipherProvider().open(arch / "archive.db", subkey(master, "db"), read_only=False)
        adb: ADBClient | None = None
        serial: str | None = None
        if not args.no_phonebook:
            try:
                adb = ADBClient(SubprocessADBRunner(str(args.adb_path) if args.adb_path else None))
                serial = adb.require_device(args.serial).serial
            except (ADBError, DeviceError) as exc:
                ui.say(f"Phone not available ({exc}); using only --vcf / --avatars if given.")
                adb = serial = None
        index, fetch = collect_phonebook(
            adb,
            serial,
            vcf=args.vcf,
            avatars=args.avatars,
            use_phone=not args.no_phonebook,
            say=ui.say,
        )
        if not index.size:
            ui.say("Nothing to add: no contact source was readable.")
            return 3
        stats = enrich_archive(
            db,
            vault,
            index,
            fetch_photo=fetch,
            progress=lambda label, d, t: ui.progress(label, d, t, "items"),
        )
        ui.progress_end()
        ui.say(
            f"Done: added {stats.named} names and {stats.photos} pictures ({stats.unmatched} of {stats.contacts} numbers not matched)."
        )
        return 0
    except (WrongKeyError, KeyError_):
        ui.say("That passphrase did not unlock this archive.")
        return 2
    except Exception:
        log.error("unexpected failure", exc_info=args.verbose)
        return 5
    finally:
        if db is not None:
            db.close()
        zeroize(master)
        zeroize(passphrase)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
