from __future__ import annotations

import ast
from pathlib import Path

import pytest

from fakes import SERIAL, FakeADBRunner
from waarchive.ingest.adb import ADBError, validate_remote_path, validate_serial
from waarchive.ingest.device import ADBClient, DeviceError


@pytest.mark.parametrize(
    "bad", ["", "a;rm -rf /", "$(id)", "x y", "a" * 80, "-s", "../x", "ab\nc", "`id`"]
)
def test_serial_rejects_malicious(bad: str) -> None:
    with pytest.raises(ADBError):
        validate_serial(bad)


@pytest.mark.parametrize("good", [SERIAL, "emulator-5554", "192.168.1.5:5555"])
def test_serial_accepts(good: str) -> None:
    assert validate_serial(good) == good


@pytest.mark.parametrize(
    "bad",
    ["/etc/passwd", "/sdcard/../data/x", "/sdcard/a;id", "/sdcard/a b", "sdcard/x", "/sdcard//x",
     "/data/data/com.whatsapp/files/key'; id; '", "/sdcard/$(id)", "/data/local/tmp/x"],
)  # fmt: skip
def test_remote_path_allowlist(bad: str) -> None:
    with pytest.raises(ADBError):
        validate_remote_path(bad)


def test_no_device() -> None:
    with pytest.raises(DeviceError, match="no Android device"):
        ADBClient(FakeADBRunner(devices=[])).require_device()


def test_unauthorized_device() -> None:
    with pytest.raises(DeviceError, match="unauthorized"):
        ADBClient(FakeADBRunner(devices=[(SERIAL, "unauthorized")])).require_device()


def test_offline_device() -> None:
    with pytest.raises(DeviceError, match="not ready"):
        ADBClient(FakeADBRunner(devices=[(SERIAL, "offline")])).require_device()


def test_multiple_devices_require_serial() -> None:
    c = ADBClient(FakeADBRunner(devices=[(SERIAL, "device"), ("OTHER1234", "device")]))
    with pytest.raises(DeviceError, match="multiple"):
        c.require_device()
    assert c.require_device("OTHER1234").serial == "OTHER1234"


def test_root_detection() -> None:
    assert ADBClient(FakeADBRunner(rooted=True)).is_rooted(SERIAL) is True
    assert ADBClient(FakeADBRunner(rooted=False)).is_rooted(SERIAL) is False
    assert ADBClient(FakeADBRunner(rooted=True, su_hangs=True)).is_rooted(SERIAL) is False


def test_discovery_prefers_newest_and_finds_media() -> None:
    root = "/sdcard/Android/media/com.whatsapp/WhatsApp"
    fs = {
        f"{root}/Databases/msgstore-2024-01-01.1.db.crypt14": b"x",
        f"{root}/Databases/msgstore-2024-03-01.1.db.crypt15": b"x",
        f"{root}/Databases/msgstore.db.crypt15": b"x",
        f"{root}/Media/WhatsApp Images/a.jpg": b"x",
    }
    lay = ADBClient(FakeADBRunner(fs=fs)).discover_storage(SERIAL, "com.whatsapp")
    assert lay is not None
    assert lay.msgstore_backups[0].endswith("/msgstore.db.crypt15")
    assert lay.msgstore_backups[-1].endswith("2024-01-01.1.db.crypt14")
    assert lay.media_dir == f"{root}/Media"


def test_discovery_legacy_path_and_nothing_found() -> None:
    fs = {"/sdcard/WhatsApp/Databases/msgstore.db.crypt14": b"x"}
    lay = ADBClient(FakeADBRunner(fs=fs)).discover_storage(SERIAL, "com.whatsapp")
    assert lay is not None and lay.root == "/sdcard/WhatsApp"
    assert ADBClient(FakeADBRunner(fs={})).discover_storage(SERIAL, "com.whatsapp") is None


def test_package_name_validated() -> None:
    with pytest.raises(ADBError):
        ADBClient(FakeADBRunner()).discover_storage(SERIAL, "com.whatsapp; id")


def test_source_never_uses_shell_or_dangerous_calls() -> None:
    """AST gate: no shell=True, eval/exec, os.system, pickle anywhere in src/."""
    bad: list[str] = []
    for p in Path("src").rglob("*.py"):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.keyword)
                and node.arg == "shell"
                and not (isinstance(node.value, ast.Constant) and node.value.value is False)
            ):
                bad.append(f"{p}:{node.lineno} shell")
            if isinstance(node, ast.Call):
                f = node.func
                name = (
                    f.id
                    if isinstance(f, ast.Name)
                    else f.attr
                    if isinstance(f, ast.Attribute)
                    else ""
                )
                if name in {"eval", "exec", "system", "popen"}:
                    bad.append(f"{p}:{node.lineno} {name}")
            if isinstance(node, ast.Import) and any(
                a.name in {"pickle", "marshal"} for a in node.names
            ):
                bad.append(f"{p}:{node.lineno} import")
    assert not bad, bad
