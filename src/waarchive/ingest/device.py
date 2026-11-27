"""Device discovery, root detection and WhatsApp storage discovery."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .adb import ADBError, ADBRunner, validate_remote_path, validate_serial
from .contacts import PhonebookEntry, read_phonebook, read_photo


class DeviceError(Exception):
    pass


@dataclass(frozen=True)
class Device:
    serial: str
    state: str  # device | unauthorized | offline | ...


BACKUP_RE = re.compile(r"^msgstore(?:-(\d{4}-\d{2}-\d{2})\.\d+)?\.db\.crypt(14|15)$")
WA_BACKUP_RE = re.compile(r"^wa(?:-(\d{4}-\d{2}-\d{2})\.\d+)?\.db\.crypt(14|15)$")


@dataclass
class StorageLayout:
    root: str
    msgstore_backups: list[str] = field(default_factory=list)  # best first
    wa_backups: list[str] = field(default_factory=list)
    media_dir: str | None = None


def shared_roots(package: str) -> tuple[str, ...]:
    if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", package):
        raise ADBError("invalid package name")
    return (f"/sdcard/Android/media/{package}/WhatsApp", "/sdcard/WhatsApp")


def private_files(package: str) -> dict[str, tuple[str, ...]]:
    base = f"/data/data/{package}"
    return {
        "key": (f"{base}/files/key", f"{base}/files/encrypted_backup.key"),
        "msgstore": (f"{base}/databases/msgstore.db",),
        "wa": (f"{base}/databases/wa.db",),
    }


def _rank(name: str, date: str | None, ver: str) -> tuple[str, str]:
    return (date or "9999-99-99", ver)  # undated rolling backup is the newest


class ADBClient:
    def __init__(self, runner: ADBRunner) -> None:
        self._r = runner

    # ---- devices -------------------------------------------------------------------
    def list_devices(self) -> list[Device]:
        res = self._r.run(["devices"])
        if res.returncode != 0:
            raise DeviceError("adb devices failed (is the adb server running?)")
        out: list[Device] = []
        for line in res.stdout.decode("utf-8", "replace").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and not line.startswith("*"):
                try:
                    out.append(Device(validate_serial(parts[0]), parts[1]))
                except ADBError:
                    continue
        return out

    def require_device(self, serial: str | None = None) -> Device:
        devices = self.list_devices()
        if serial is not None:
            validate_serial(serial)
            devices = [d for d in devices if d.serial == serial]
        if not devices:
            raise DeviceError("no Android device found; enable USB debugging and reconnect")
        if len(devices) > 1:
            raise DeviceError("multiple devices connected; pass --serial")
        dev = devices[0]
        if dev.state == "unauthorized":
            raise DeviceError(
                "device is unauthorized: unlock the phone and accept the USB debugging prompt"
            )
        if dev.state != "device":
            raise DeviceError(f"device not ready (state: {dev.state})")
        return dev

    # ---- root ----------------------------------------------------------------------
    def is_rooted(self, serial: str) -> bool:
        validate_serial(serial)
        try:
            res = self._r.run(["-s", serial, "shell", "su -c 'id'"], timeout=20.0)
        except ADBError:
            return False  # e.g. a root-manager prompt that was never answered
        return res.returncode == 0 and b"uid=0" in res.stdout

    # ---- listing / pulling ---------------------------------------------------------
    def list_dir(self, serial: str, remote: str) -> list[str]:
        validate_serial(serial)
        validate_remote_path(remote)
        res = self._r.run(["-s", serial, "shell", "ls", "-1", remote])
        if res.returncode != 0:
            return []
        return [
            ln.strip() for ln in res.stdout.decode("utf-8", "replace").splitlines() if ln.strip()
        ]

    def read_phonebook(self, serial: str) -> list[PhonebookEntry]:
        return read_phonebook(self._r, serial)

    def read_contact_photo(self, serial: str, contact_id: int) -> bytes | None:
        return read_photo(self._r, serial, contact_id)

    def remote_size(self, serial: str, remote: str) -> int | None:
        """Total bytes below a remote path (`du -sk`, rounded to KB); None if the phone will not say."""
        validate_serial(serial)
        validate_remote_path(remote)
        res = self._r.run(["-s", serial, "shell", "du", "-sk", remote], timeout=600.0)
        if res.returncode != 0:
            return None
        m = re.match(rb"\s*(\d+)", res.stdout)
        return int(m.group(1)) * 1024 if m else None

    def pull(self, serial: str, remote: str, local: Path) -> bool:
        validate_serial(serial)
        validate_remote_path(remote)
        res = self._r.run(["-s", serial, "pull", remote, str(local)], timeout=3600.0)
        return res.returncode == 0

    def root_cat(self, serial: str, remote: str, dest: Path) -> bool:
        """Copy a private file via `su -c cat`, streaming straight to a 0600 local file."""
        validate_serial(serial)
        validate_remote_path(remote)
        rc = self._r.run_to_file(["-s", serial, "exec-out", f"su -c 'cat {remote}'"], dest)
        return rc == 0 and dest.exists() and dest.stat().st_size > 0

    # ---- discovery -----------------------------------------------------------------
    def discover_storage(self, serial: str, package: str) -> StorageLayout | None:
        for root in shared_roots(package):
            entries = self.list_dir(serial, root)
            if not entries:
                continue
            layout = StorageLayout(root=root)
            ms: list[tuple[tuple[str, str], str]] = []
            wa: list[tuple[tuple[str, str], str]] = []
            for sub in ("Databases", "Backups", ""):
                base = f"{root}/{sub}" if sub else root
                for name in self.list_dir(serial, base):
                    m = BACKUP_RE.fullmatch(name)
                    if m:
                        ms.append((_rank(name, m.group(1), m.group(2)), f"{base}/{name}"))
                        continue
                    w = WA_BACKUP_RE.fullmatch(name)
                    if w:
                        wa.append((_rank(name, w.group(1), w.group(2)), f"{base}/{name}"))
            layout.msgstore_backups = [p for _, p in sorted(ms, reverse=True)]
            layout.wa_backups = [p for _, p in sorted(wa, reverse=True)]
            if "Media" in entries:
                layout.media_dir = f"{root}/Media"
            if layout.msgstore_backups or layout.media_dir:
                return layout
        return None
