"""End-to-end orchestration: device -> (root check) -> pull -> decrypt -> normalize -> archive."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..keys import KdfParams, derive_master, subkey, write_params
from ..media_vault import MediaVault
from ..secure_fs import secure_tempdir, zeroize
from .archive import DatabaseProvider
from .contacts import PhonebookEntry, PhonebookIndex, collect_phonebook, enrich_archive
from .crypt import (
    SQLITE_MAGIC,
    DecryptError,
    decrypt_backup,
    key_candidates_from_file,
    parse_hex_key,
)
from .device import ADBClient, Device, DeviceError, private_files
from .normalize import IngestStats, Normalizer, open_source_ro
from .progress import DirWatcher
from .ui import UI, UNROOTED_ALERT

log = logging.getLogger(__name__)

MAX_KEY_ATTEMPTS = 3
MAX_BUNDLE_FILE = 64 * 1024**3


class IngestError(Exception):
    exit_code = 5


class UsageError(IngestError):
    exit_code = 2


class DeviceFailure(IngestError):
    exit_code = 3


class DecryptFailure(IngestError):
    exit_code = 4


@dataclass
class IngestConfig:
    out_dir: Path
    package: str = "com.whatsapp"
    serial: str | None = None
    bundle: Path | None = None
    vcf: Path | None = None  # contacts export (.vcf) with names and photos
    avatars: Path | None = None  # folder of pictures named by phone number
    use_phonebook: bool = True  # read names/photos from the phone's address book
    kdf_overrides: dict[str, int] | None = None  # tests only: cheap Argon2 costs


@dataclass
class IngestResult:
    stats: IngestStats
    rooted: bool
    archive: Path


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC
    except OSError:
        return False


def _read_bundle_file(bundle: Path, name: str) -> Path | None:
    p = bundle / name
    if p.is_symlink() or not p.is_file():
        return None
    if p.stat().st_size > MAX_BUNDLE_FILE:
        raise UsageError("bundle file too large")
    return p


class Pipeline:
    def __init__(
        self, adb: ADBClient | None, ui: UI, provider: DatabaseProvider, cfg: IngestConfig
    ) -> None:
        self.adb, self.ui, self.provider, self.cfg = adb, ui, provider, cfg

    # ------------------------------------------------------------------ helpers
    def _copy_bundle(self, bundle: Path, tmp: Path) -> None:
        import shutil  # noqa: PLC0415

        bundle = bundle.resolve()
        if not bundle.is_dir():
            raise UsageError("bundle path must be an existing directory")
        for name in ("key", "encrypted_backup.key", "msgstore.db", "wa.db"):
            src = _read_bundle_file(bundle, name)
            if src:
                dest = tmp / ("bundle_" + name)
                shutil.copyfile(src, dest)
                os.chmod(dest, 0o600)

    def _ask_key(self) -> list[bytearray]:
        for attempt in range(1, MAX_KEY_ATTEMPTS + 1):
            raw = self.ui.ask_secret("64-digit end-to-end encrypted backup key (input hidden): ")
            try:
                return [parse_hex_key(raw.decode("utf-8", "replace"))]
            except DecryptError as exc:
                self.ui.alert(f"Invalid key ({exc}). Attempt {attempt}/{MAX_KEY_ATTEMPTS}.")
            finally:
                zeroize(raw)
        raise UsageError("no valid key supplied")

    def _decrypt_with(
        self, src: Path, dest: Path, keys: list[bytearray], label: str = "Decrypting"
    ) -> bool:
        try:
            decrypt_backup(src, dest, keys, on_progress=lambda d, t: self.ui.progress(label, d, t))
            return True
        except DecryptError:
            return False
        finally:
            self.ui.progress_end()

    def _pull(self, serial: str, remote: str, local: Path, label: str) -> bool:
        """adb pull with a live progress bar (the bytes that have landed locally vs. the size on the phone)."""
        adb = self._adb()
        total = adb.remote_size(serial, remote)
        self.ui.progress(label, 0, total)
        with DirWatcher(local, lambda n: self.ui.progress(label, n, total)):
            ok = adb.pull(serial, remote, local)
        self.ui.progress_end()
        return ok

    # --------------------------------------------------------------------- main
    def run(self, passphrase: bytearray) -> IngestResult:
        try:
            return self._run(passphrase)
        finally:
            zeroize(passphrase)
            log.info("ingest finished; temporary artifacts wiped")

    def _run(self, passphrase: bytearray) -> IngestResult:
        cfg = self.cfg
        cfg.out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        archive_path = cfg.out_dir / "archive.db"
        if archive_path.exists():
            raise UsageError(
                "archive.db already exists in the output directory; refusing to overwrite"
            )

        with secure_tempdir() as tmp:
            media_root: Path | None = None
            serial: str | None = None
            rooted = False
            keys: list[bytearray] = []
            msgstore_plain: Path | None = None
            msgstore_crypt: Path | None = None
            wa_plain: Path | None = None
            wa_crypt: Path | None = None
            try:
                if self.adb is not None:
                    dev = self._device()
                    serial = dev.serial
                    rooted = self.adb.is_rooted(dev.serial)
                    if rooted:
                        self.ui.say("Device is rooted: extracting private WhatsApp files.")
                        keys, msgstore_plain, wa_plain = self._pull_private(dev.serial, tmp)
                        media_root = self._pull_media(dev.serial, tmp)
                    else:
                        self.ui.alert(UNROOTED_ALERT)
                        msgstore_crypt, wa_crypt, media_root = self._pull_shared(dev.serial, tmp)

                if not rooted:
                    keys, msgstore_plain, wa_plain = self._unrooted_secrets(tmp, keys)

                if msgstore_plain is None:
                    if msgstore_crypt is None:
                        raise DecryptFailure("no WhatsApp database found to ingest")
                    if not keys:
                        raise DecryptFailure("no decryption key available")
                    msgstore_plain = tmp / "msgstore.db"
                    if not self._decrypt_with(
                        msgstore_crypt, msgstore_plain, keys, "Decrypting chat backup"
                    ):
                        raise DecryptFailure(
                            "decryption failed: wrong key, corrupt file or unsupported format"
                        )
                if wa_plain is None and wa_crypt is not None and keys:
                    cand = tmp / "wa.db"
                    if self._decrypt_with(wa_crypt, cand, keys):
                        wa_plain = cand
                    else:
                        self.ui.say("Contacts backup could not be decrypted; using phone numbers.")
                if wa_plain is None:
                    self.ui.say("No contacts database available: showing formatted phone numbers.")
                if not _is_sqlite(msgstore_plain):
                    raise DecryptFailure("message database is not a valid SQLite file")
            finally:
                for k in keys:
                    zeroize(k)

            phonebook = collect_phonebook(
                self.adb,
                serial,
                vcf=self.cfg.vcf,
                avatars=self.cfg.avatars,
                use_phone=self.cfg.use_phonebook,
                say=self.ui.say,
            )
            stats = self._build_archive(
                passphrase, msgstore_plain, wa_plain, media_root, archive_path, phonebook
            )
        return IngestResult(stats, rooted, archive_path)

    # ------------------------------------------------------------- device paths
    def _adb(self) -> ADBClient:
        if self.adb is None:
            raise UsageError("ADB is not available in offline bundle mode")
        return self.adb

    def _device(self) -> Device:
        adb = self._adb()
        try:
            return adb.require_device(self.cfg.serial)
        except DeviceError as exc:
            raise DeviceFailure(str(exc)) from exc

    def _pull_private(self, serial: str, tmp: Path) -> tuple[list[bytearray], Path, Path | None]:
        adb = self._adb()
        files = private_files(self.cfg.package)
        keys: list[bytearray] = []
        for remote in files["key"]:
            dest = tmp / "device_key"
            if adb.root_cat(serial, remote, dest):
                keys += key_candidates_from_file(dest.read_bytes())
                break
        ms = tmp / "device_msgstore.db"
        if not adb.root_cat(serial, files["msgstore"][0], ms) or not _is_sqlite(ms):
            raise DeviceFailure("could not read msgstore.db via root")
        wa: Path | None = tmp / "device_wa.db"
        if not adb.root_cat(serial, files["wa"][0], wa) or not _is_sqlite(wa):  # type: ignore[arg-type]
            wa = None
        return keys, ms, wa

    def _pull_media(self, serial: str, tmp: Path) -> Path | None:
        adb = self._adb()
        layout = adb.discover_storage(serial, self.cfg.package)
        if not layout or not layout.media_dir:
            return None
        dest = tmp / "media_pull"
        dest.mkdir(mode=0o700)
        return (
            dest
            if self._pull(serial, layout.media_dir, dest, "Copying photos, videos, voice notes")
            else None
        )

    def _pull_shared(self, serial: str, tmp: Path) -> tuple[Path | None, Path | None, Path | None]:
        adb = self._adb()
        layout = adb.discover_storage(serial, self.cfg.package)
        if layout is None:
            self.ui.say("No WhatsApp data found on shared storage.")
            return None, None, None
        ms: Path | None = None
        wa: Path | None = None
        if layout.msgstore_backups:
            remote = layout.msgstore_backups[0]
            ms = tmp / ("pulled_" + remote.rsplit("/", 1)[-1])
            ok = self._pull(serial, remote, ms, "Copying chat backup")
            ms = ms if ok and ms.exists() else None
        if layout.wa_backups:
            remote = layout.wa_backups[0]
            wa = tmp / ("pulled_" + remote.rsplit("/", 1)[-1])
            ok = self._pull(serial, remote, wa, "Copying contacts backup")
            wa = wa if ok and wa.exists() else None
        media: Path | None = None
        if layout.media_dir:
            media = tmp / "media_pull"
            media.mkdir(mode=0o700)
            media = (
                media
                if self._pull(
                    serial, layout.media_dir, media, "Copying photos, videos, voice notes"
                )
                else None
            )
        return ms, wa, media

    def _unrooted_secrets(
        self, tmp: Path, keys: list[bytearray]
    ) -> tuple[list[bytearray], Path | None, Path | None]:
        bundle = self.cfg.bundle
        if bundle is None:
            choice = self.ui.ask(
                "Choose how to continue:\n  [1] enter my 64-digit E2EE backup key\n"
                "  [2] use a local folder with key / msgstore.db / wa.db\n> "
            ).strip()
            if choice == "1":
                return self._ask_key(), None, None
            if choice == "2":
                bundle = Path(self.ui.ask("Path to exported bundle folder: ").strip()).expanduser()
            else:
                raise UsageError("no option selected")
        self._copy_bundle(bundle, tmp)
        ms = tmp / "bundle_msgstore.db"
        wa = tmp / "bundle_wa.db"
        for name in ("bundle_key", "bundle_encrypted_backup.key"):
            f = tmp / name
            if f.is_file():
                try:
                    keys += key_candidates_from_file(f.read_bytes())
                except DecryptError:
                    self.ui.alert("A key file in the bundle was not recognised.")
        if not keys and not ms.is_file():
            raise UsageError("bundle contains neither a usable key nor a msgstore.db")
        return keys, ms if ms.is_file() else None, wa if wa.is_file() else None

    # ----------------------------------------------------------------- archive
    def _build_archive(
        self,
        passphrase: bytearray,
        msgstore: Path,
        wa: Path | None,
        media_root: Path | None,
        out: Path,
        phonebook: tuple[PhonebookIndex, Callable[[PhonebookEntry], bytes | None] | None]
        | None = None,
    ) -> IngestStats:
        params = KdfParams.fresh(**(self.cfg.kdf_overrides or {}))
        master = derive_master(passphrase, params)
        try:
            db_key = subkey(master, "db")
            vault = MediaVault(
                self.cfg.out_dir / "media", subkey(master, "media"), subkey(master, "media-name")
            )
            write_params(self.cfg.out_dir / "archive.kdf.json", params)
            dst = self.provider.create(out, db_key)
            src = open_source_ro(msgstore)
            wa_conn: sqlite3.Connection | None = (
                open_source_ro(wa) if wa and _is_sqlite(wa) else None
            )
            try:
                stats = Normalizer(
                    src,
                    dst,
                    wa=wa_conn,
                    media_root=media_root,
                    vault=vault,
                    progress=lambda label, done, total: self.ui.progress(
                        label, done, total, "items"
                    ),
                ).run()
                self.ui.progress_end()
                if phonebook is not None and phonebook[0].size:
                    done = enrich_archive(
                        dst,
                        vault,
                        phonebook[0],
                        fetch_photo=phonebook[1],
                        progress=lambda label, d, t: self.ui.progress(label, d, t, "items"),
                    )
                    self.ui.progress_end()
                    stats.names_added, stats.pictures_added = done.named, done.photos
                    self.ui.say(
                        f"Contacts: added {done.named} names and {done.photos} pictures "
                        f"({done.unmatched} of {done.contacts} numbers were not in your address book)."
                    )
            finally:
                src.close()
                if wa_conn:
                    wa_conn.close()
                dst.close()
        finally:
            zeroize(master)
        log.info(
            "archive built: %d chats, %d messages, %d media stored (%s schema)",
            stats.chats, stats.messages, stats.media_stored, stats.schema,
        )  # fmt: skip
        return stats
