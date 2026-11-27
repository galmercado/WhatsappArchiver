"""Command-line entry point. Secrets are accepted only via prompt or environment variables,
never argv (argv is visible to other local users via the process list)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..keys import KeyError_, check_passphrase
from ..logsafe import configure_logging
from ..secure_fs import zeroize
from . import existing
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
    p.add_argument(
        "--replace",
        action="store_true",
        help="if an archive already exists, rebuild it without asking (the old one is kept as a backup folder)",
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


@dataclass
class _Plan:
    exit_code: int | None = None  # set when the user's request was fully handled here
    build_dir: Path | None = None
    passphrase: bytearray | None = None


MENU = (
    "What would you like to do?\n"
    "  [1] Check what is inside it (asks for your vault passphrase)\n"
    "  [2] Add contact names and pictures to it (no need to copy the phone again)\n"
    "  [3] Rebuild it from the phone (the old one is kept as a backup folder)\n"
    "  [4] Cancel\n> "
)


def _enrich_argv(args: argparse.Namespace) -> list[str]:
    argv = ["--archive", str(args.out)]
    for flag, value in (
        ("--serial", args.serial),
        ("--adb-path", args.adb_path),
        ("--vcf", args.vcf),
        ("--avatars", args.avatars),
    ):
        if value:
            argv += [flag, str(value)]
    return argv + (["--no-phonebook"] if args.no_phonebook else [])


def _handle_existing(args: argparse.Namespace, ui: UI) -> _Plan:  # noqa: PLR0911 - one return per menu choice
    """An archive is already in --out: never overwrite it silently. Ask what to do."""
    out: Path = args.out
    if args.replace:
        choice = "3"
    elif os.environ.get(PASSPHRASE_ENV):  # unattended run: refuse rather than guess
        ui.say(
            f"An archive already exists in '{out}'. Run again with --replace to rebuild it, or pick another --out folder."
        )
        return _Plan(exit_code=2)
    else:
        ui.say(f"An archive already exists in '{out}'.")
        choice = ui.ask(MENU).strip()

    if choice == "1":
        pw = existing.ask_existing_passphrase(
            out, ui, "Vault passphrase of this archive (input hidden): "
        )
        if pw is None:
            return _Plan(exit_code=2)
        try:
            for line in existing.summarize(out, pw).lines(out):
                ui.say(line)
        finally:
            zeroize(pw)
        return _Plan(exit_code=0)
    if choice == "2":
        from .enrich_cli import main as enrich_main  # noqa: PLC0415

        return _Plan(exit_code=enrich_main(_enrich_argv(args), ui=ui))
    if choice == "3":
        keep: bytearray | None = None
        if not os.environ.get(PASSPHRASE_ENV):
            ui.say("Choose the vault passphrase for the new archive.")
            keep = existing.ask_existing_passphrase(
                out,
                ui,
                "Type your EXISTING vault passphrase to keep using it, or just press Enter to choose a new one: ",
                blank_ok=True,
            )
            if keep is None and ui.ask(
                "Choose a new passphrase instead? [y/N] "
            ).strip().lower() not in ("y", "yes"):
                ui.say("Nothing changed.")
                return _Plan(exit_code=0)
        build = existing.build_dir_for(out)
        existing.discard(build)  # leftover from an earlier attempt that was interrupted
        return _Plan(build_dir=build, passphrase=keep)
    ui.say("Nothing changed.")
    return _Plan(exit_code=0)


def main(argv: Sequence[str] | None = None, *, ui: UI | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    log = logging.getLogger("waarchive")
    ui = ui or TerminalUI()
    passphrase: bytearray | None = None
    build_dir: Path = args.out
    swapped = False
    try:
        if existing.exists(args.out):
            plan = _handle_existing(args, ui)
            if plan.exit_code is not None:
                return plan.exit_code
            build_dir = plan.build_dir or args.out
            passphrase = plan.passphrase
        passphrase = passphrase or _get_passphrase(ui)
        check_passphrase(passphrase)
        adb_exe = str(args.adb_path) if args.adb_path else None
        adb = None if args.bundle else ADBClient(SubprocessADBRunner(adb_exe))
        cfg = IngestConfig(
            out_dir=build_dir,
            package=args.package,
            serial=args.serial,
            bundle=args.bundle,
            vcf=args.vcf,
            avatars=args.avatars,
            use_phonebook=not args.no_phonebook,
        )
        result = Pipeline(adb, ui, SQLCipherProvider(), cfg).run(passphrase)
        if build_dir != args.out:
            backup = existing.swap_in(build_dir, args.out)
            swapped = True
            ui.say(
                f"The previous archive was kept as '{backup}'. Delete that folder once you are happy with the new one."
            )
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
        if build_dir != args.out and not swapped:
            existing.discard(
                build_dir
            )  # a failed rebuild must not leave debris; the old archive is untouched
    final = args.out / "archive.db"
    ui.say(
        f"Done: {result.stats.chats} chats, {result.stats.messages} messages, "
        f"{result.stats.media_stored} media files, {result.stats.names_added} contact names, "
        f"{result.stats.pictures_added} pictures. Archive: {final}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
