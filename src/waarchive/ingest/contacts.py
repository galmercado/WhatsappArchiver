"""Contact names and pictures for an UNROOTED phone.

WhatsApp keeps its own contact database and cached profile pictures in private storage, which Android does
not let a computer read. What *is* readable without root, and is the user's own data:

* the phone's address book (names + numbers + saved contact photos) through Android's contacts provider,
* a contacts export (.vcf) from the Contacts app (names, numbers and photos),
* a folder of pictures the user supplies, named by phone number.

Names are matched to WhatsApp JIDs by phone number (international or national format).
"""

from __future__ import annotations

import base64
import hashlib
import quopri
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .adb import ADBRunner, validate_serial

if TYPE_CHECKING:
    from ..media_vault import MediaVault
    from .archive import DBConnection

MAX_PHOTO = 3 * 1024 * 1024
MAX_VCF = 256 * 1024 * 1024
MIN_NUMBER_DIGITS = 7
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class PhonebookError(Exception):
    pass


class PhoneContacts(Protocol):
    """What the importer needs from a connected phone (ADBClient implements this)."""

    def read_phonebook(self, serial: str) -> list[PhonebookEntry]: ...
    def read_contact_photo(self, serial: str, contact_id: int) -> bytes | None: ...


@dataclass(frozen=True)
class PhonebookEntry:
    name: str  # "" for picture-only entries
    numbers: tuple[str, ...]  # digits only
    photo: bytes | None = None
    source_id: int | None = None  # Android contact id, used to fetch the photo on demand


@dataclass
class EnrichStats:
    contacts: int = 0
    named: int = 0
    photos: int = 0
    unmatched: int = 0


def digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def sniff_image(data: bytes) -> str | None:
    """MIME type from magic bytes; only formats a browser can show safely. Everything else is rejected."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def avatar_rel(jid: str) -> str:
    """Opaque vault path for a contact's picture."""
    return "avatars/" + hashlib.sha256(jid.encode("utf-8", "replace")).hexdigest()[:32]


# ------------------------------------------------------------------------------ matching
def _key(d: str) -> str | None:
    return d[-9:] if len(d) >= MIN_NUMBER_DIGITS else None


class PhonebookIndex:
    """Look up an address-book entry from a WhatsApp JID, tolerant of national/international formats."""

    def __init__(self, entries: list[PhonebookEntry]) -> None:
        self._by_key: dict[str, list[tuple[str, PhonebookEntry]]] = {}
        for e in entries:
            for num in e.numbers:
                k = _key(num)
                if k:
                    self._by_key.setdefault(k, []).append((num, e))
        self.size = len(entries)

    def lookup(self, jid: str) -> PhonebookEntry | None:
        user = jid.split("@", 1)[0]
        if not user.isdigit():
            return None
        k = _key(user)
        if k is None:
            return None
        agree = []
        for num, e in self._by_key.get(k, []):
            core = num.lstrip("0")
            if core and (user.endswith(core) or core.endswith(user)):
                agree.append(e)
        names = {e.name for e in agree if e.name}
        if len(names) > 1:  # two different people share the number's tail: refuse to guess
            return None
        if not agree:
            return None
        name = next(iter(names), "")
        photo = next((e.photo for e in agree if e.photo), None)
        source_id = next(
            (e.source_id for e in agree if e.name == name and e.source_id is not None), None
        )
        return PhonebookEntry(name=name, numbers=agree[0].numbers, photo=photo, source_id=source_id)


# --------------------------------------------------------------------------- vCard export
def _qp(value: str, charset: str) -> str:
    try:
        return quopri.decodestring(value.encode("ascii", "ignore")).decode(
            charset or "utf-8", "replace"
        )
    except (ValueError, LookupError):
        return value


def parse_vcf(text: str) -> list[PhonebookEntry]:
    """vCard 2.1/3.0/4.0 (as exported by Samsung Contacts, Google Contacts, iOS)."""
    text = re.sub(r"\r?\n[ \t]", "", text)  # folded lines (also wraps base64 photos)
    lines: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = pending + raw.rstrip("\r")
        # quoted-printable soft breaks ("=" at end of line) apply ONLY to QP properties; base64 padding also ends in "="
        if line.endswith("=") and "QUOTED-PRINTABLE" in line.split(":", 1)[0].upper():
            pending = line[:-1]
            continue
        pending = ""
        lines.append(line)
    if pending:
        lines.append(pending)
    out: list[PhonebookEntry] = []
    name = ""
    structured = ""
    nums: list[str] = []
    photo: bytes | None = None
    in_card = False
    for line in lines:
        up = line.upper()
        if up == "BEGIN:VCARD":
            in_card, name, structured, nums, photo = True, "", "", [], None
            continue
        if up == "END:VCARD":
            if in_card and nums:
                out.append(
                    PhonebookEntry(
                        name=name or structured, numbers=tuple(dict.fromkeys(nums)), photo=photo
                    )
                )
            in_card = False
            continue
        if not in_card or ":" not in line:
            continue
        head, _, value = line.partition(":")
        params = head.upper().split(";")
        prop = params[0].split(".")[-1]  # drop group prefix "item1.TEL"
        charset = next((p.split("=", 1)[1] for p in params if p.startswith("CHARSET=")), "utf-8")
        if "ENCODING=QUOTED-PRINTABLE" in params or "QUOTED-PRINTABLE" in params:
            value = _qp(value, charset)
        if prop == "FN":
            name = value.strip()
        elif prop == "N" and not structured:
            parts = [*value.split(";"), "", ""][:2]
            structured = " ".join(p for p in (parts[1].strip(), parts[0].strip()) if p)
        elif prop == "TEL":
            d = digits(value)
            if len(d) >= MIN_NUMBER_DIGITS:
                nums.append(d)
        elif (
            prop == "PHOTO"
            and photo is None
            and any(p in ("ENCODING=B", "ENCODING=BASE64", "BASE64", "B") for p in params)
        ):
            try:
                data = base64.b64decode(re.sub(r"\s", "", value), validate=False)
            except ValueError:
                continue
            if len(data) <= MAX_PHOTO and sniff_image(data):
                photo = data
    return out


def load_vcf(path: Path) -> list[PhonebookEntry]:
    if not path.is_file() or path.is_symlink():
        raise PhonebookError("contacts file not found")
    if path.stat().st_size > MAX_VCF:
        raise PhonebookError("contacts file is too large")
    return parse_vcf(path.read_bytes().decode("utf-8", "replace"))


def load_avatar_dir(path: Path) -> list[PhonebookEntry]:
    """Pictures named by phone number, e.g. `972501234567.jpg` or `+1 555 123 4567.png`."""
    if not path.is_dir():
        raise PhonebookError("pictures folder not found")
    out: list[PhonebookEntry] = []
    for f in sorted(path.iterdir()):
        if f.suffix.lower() not in IMAGE_SUFFIXES or f.is_symlink() or not f.is_file():
            continue
        num = digits(f.stem.split("@", 1)[0])
        if len(num) < MIN_NUMBER_DIGITS or f.stat().st_size > MAX_PHOTO:
            continue
        data = f.read_bytes()
        if sniff_image(data):
            out.append(PhonebookEntry(name="", numbers=(num,), photo=data))
    return out


# ------------------------------------------------------------------- phone address book (adb)
_ROW = re.compile(r"^Row: \d+ contact_id=(\d+), display_name=(.*), data1=(.*)$")
_CONTACTS = "content://com.android.contacts"


def read_phonebook(runner: ADBRunner, serial: str) -> list[PhonebookEntry]:
    """Names and numbers from the phone's address book. Works without root: adb's shell user may read contacts."""
    validate_serial(serial)
    res = runner.run(
        [
            "-s",
            serial,
            "shell",
            f"content query --uri {_CONTACTS}/data/phones --projection contact_id:display_name:data1",
        ],
        timeout=180.0,
    )
    text = res.stdout.decode("utf-8", "replace")
    first = text.splitlines()[0] if text else ""
    if res.returncode != 0 or "Permission Denial" in text or "Exception" in first:
        raise PhonebookError("the phone refused to share its address book")
    grouped: dict[int, tuple[str, list[str]]] = {}
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        cid, name, number = int(m.group(1)), m.group(2).strip(), digits(m.group(3))
        if name in ("", "NULL") or len(number) < MIN_NUMBER_DIGITS:
            continue
        grouped.setdefault(cid, (name, []))[1].append(number)
    return [
        PhonebookEntry(name=n, numbers=tuple(dict.fromkeys(nums)), source_id=cid)
        for cid, (n, nums) in grouped.items()
    ]


def read_photo(runner: ADBRunner, serial: str, contact_id: int) -> bytes | None:
    """The contact's saved photo (full size, else thumbnail) or None."""
    validate_serial(serial)
    cid = int(contact_id)
    for kind in ("display_photo", "photo"):
        res = runner.run(
            ["-s", serial, "exec-out", f"content read --uri {_CONTACTS}/contacts/{cid}/{kind}"],
            timeout=30.0,
        )
        data = res.stdout
        if res.returncode == 0 and 0 < len(data) <= MAX_PHOTO and sniff_image(data):
            return data
    return None


# ------------------------------------------------------------------------- enrich the archive
def enrich_archive(
    db: DBConnection,
    vault: MediaVault | None,
    index: PhonebookIndex,
    *,
    fetch_photo: Callable[[PhonebookEntry], bytes | None] | None = None,
    progress: Callable[[str, int, int | None], None] | None = None,
) -> EnrichStats:
    """Fill in names (only where WhatsApp's own saved-contact name is missing) and pictures."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(contact)").fetchall()}
    if "avatar_mime" not in cols:  # archives made before pictures existed
        db.execute("ALTER TABLE contact ADD COLUMN avatar_mime TEXT")
    rows = db.execute(
        "SELECT jid, display_name, source, avatar_mime FROM contact WHERE is_group = 0"
    ).fetchall()
    stats = EnrichStats(contacts=len(rows))
    for i, (jid, name, source, has_avatar) in enumerate(rows, 1):
        entry = index.lookup(jid)
        if entry is None:
            stats.unmatched += 1
        else:
            if entry.name and (name is None or source in ("derived", "push")):
                db.execute(
                    "UPDATE contact SET display_name = ?, source = 'phonebook' WHERE jid = ?",
                    (entry.name[:256], jid),
                )
                stats.named += 1
            if has_avatar is None and vault is not None:
                photo = entry.photo or (fetch_photo(entry) if fetch_photo else None)
                mime = sniff_image(photo) if photo else None
                if photo and mime and len(photo) <= MAX_PHOTO:
                    vault.store_bytes(avatar_rel(jid), photo)
                    db.execute("UPDATE contact SET avatar_mime = ? WHERE jid = ?", (mime, jid))
                    stats.photos += 1
        if progress and (i % 10 == 0 or i == len(rows)):
            progress("Matching contacts", i, len(rows))
    db.commit()
    return stats


def collect_phonebook(
    adb: PhoneContacts | None,
    serial: str | None,
    *,
    vcf: Path | None,
    avatars: Path | None,
    use_phone: bool,
    say: Callable[[str], None],
) -> tuple[PhonebookIndex, Callable[[PhonebookEntry], bytes | None] | None]:
    """Gather address-book entries from every available source. Never fatal: problems are reported and skipped."""
    entries: list[PhonebookEntry] = []
    fetch: Callable[[PhonebookEntry], bytes | None] | None = None
    if use_phone and adb is not None and serial is not None:
        say("Reading contact names from the phone's address book (no root needed)...")
        try:
            got = adb.read_phonebook(serial)
            say(f"  found {len(got)} contacts on the phone.")
            entries += got

            def fetch(e: PhonebookEntry) -> bytes | None:
                return (
                    adb.read_contact_photo(serial, e.source_id) if e.source_id is not None else None
                )

        except PhonebookError:
            say(
                "  The phone did not share its address book. Export your contacts to a .vcf file and use --vcf (see the tutorial)."
            )
    for label, path, loader in (
        ("contacts file", vcf, load_vcf),
        ("pictures folder", avatars, load_avatar_dir),
    ):
        if path is not None:
            try:
                got = loader(path)
                say(f"Read {len(got)} entries from your {label}.")
                entries += got
            except PhonebookError as exc:
                say(f"Could not read your {label}: {exc}.")
    return PhonebookIndex(entries), fetch


__all__ = [
    "EnrichStats", "PhonebookEntry", "PhonebookError", "PhonebookIndex", "avatar_rel", "collect_phonebook",
    "digits", "enrich_archive", "load_avatar_dir", "load_vcf", "parse_vcf", "read_phonebook", "read_photo",
    "sniff_image",
]  # fmt: skip
