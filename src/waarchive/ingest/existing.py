"""Detect and work with an archive that already exists in the output folder."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from ..keys import KeyError_, derive_master, read_params, subkey
from ..secure_fs import zeroize
from .archive import DBConnection, SQLCipherProvider, WrongKeyError
from .progress import dir_size, human_bytes
from .ui import UI

MAX_ATTEMPTS = 3


@dataclass
class ArchiveSummary:
    chats: int
    messages: int
    media: int
    contacts: int
    named: int
    pictures: int
    size_bytes: int

    def lines(self, where: Path) -> list[str]:
        return [
            f"Archive '{where}' opens correctly ({human_bytes(self.size_bytes)} on disk):",
            f"  {self.chats:,} chats, {self.messages:,} messages, {self.media:,} photos/videos/voice notes/documents",
            f"  {self.contacts:,} contacts: {self.named:,} with names, {self.pictures:,} with pictures",
        ]


def exists(out: Path) -> bool:
    return (out / "archive.db").is_file()


def open_with_passphrase(
    arch: Path, passphrase: bytes | bytearray, *, read_only: bool = True
) -> DBConnection:
    """Open the archive's database; raises WrongKeyError / KeyError_ for a wrong passphrase or damaged files."""
    master = derive_master(passphrase, read_params(arch / "archive.kdf.json"))
    try:
        return SQLCipherProvider().open(
            arch / "archive.db", subkey(master, "db"), read_only=read_only
        )
    finally:
        zeroize(master)


def verify_passphrase(arch: Path, passphrase: bytes | bytearray) -> bool:
    try:
        open_with_passphrase(arch, passphrase).close()
    except (WrongKeyError, KeyError_):
        return False
    return True


def summarize(arch: Path, passphrase: bytes | bytearray) -> ArchiveSummary:
    db = open_with_passphrase(arch, passphrase)
    try:

        def one(sql: str) -> int:
            return int(db.execute(sql).fetchone()[0])

        has_pics = any(
            r[1] == "avatar_mime" for r in db.execute("PRAGMA table_info(contact)").fetchall()
        )
        return ArchiveSummary(
            chats=one("SELECT COUNT(*) FROM chat"),
            messages=one("SELECT COUNT(*) FROM message"),
            media=one("SELECT COUNT(*) FROM message_media WHERE stored = 1"),
            contacts=one("SELECT COUNT(*) FROM contact WHERE is_group = 0"),
            named=one(
                "SELECT COUNT(*) FROM contact WHERE is_group = 0 AND display_name IS NOT NULL"
            ),
            pictures=one("SELECT COUNT(*) FROM contact WHERE avatar_mime IS NOT NULL")
            if has_pics
            else 0,
            size_bytes=dir_size(arch),
        )
    finally:
        db.close()


def ask_existing_passphrase(
    arch: Path, ui: UI, prompt: str, *, blank_ok: bool = False
) -> bytearray | None:
    """Ask for the archive's current passphrase (3 tries). Blank returns None when *blank_ok*."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        pw = ui.ask_secret(prompt)
        if not pw and blank_ok:
            return None
        if pw and verify_passphrase(arch, pw):
            return pw
        zeroize(pw)
        ui.alert(f"That is not this archive's vault passphrase (attempt {attempt}/{MAX_ATTEMPTS}).")
    return None


def build_dir_for(out: Path) -> Path:
    return out.with_name(out.name + ".new")


def discard(build_dir: Path) -> None:
    """Remove a half-built archive folder (only ever our own `*.new` sibling)."""
    if build_dir.name.endswith(".new") and build_dir.is_dir() and not build_dir.is_symlink():
        shutil.rmtree(build_dir, ignore_errors=True)


def swap_in(new: Path, out: Path) -> Path:
    """Put the freshly built archive in place and keep the old one as `<name>.previous-<time>`."""
    backup = out.with_name(f"{out.name}.previous-{time.strftime('%Y%m%d-%H%M%S')}")
    out.rename(backup)
    try:
        new.rename(out)
    except OSError:
        backup.rename(out)  # put the old archive back: never leave the user without one
        raise
    return backup
