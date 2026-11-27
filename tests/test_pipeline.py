from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import pytest

from conftest import FAST_KDF, PASSPHRASE
from fakes import SERIAL, FakeADBRunner, ScriptedUI
from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest.archive import SQLCipherProvider
from waarchive.ingest.device import ADBClient
from waarchive.ingest.pipeline import (
    DecryptFailure,
    DeviceFailure,
    IngestConfig,
    Pipeline,
    UsageError,
)
from waarchive.keys import derive_master, read_params, subkey
from waarchive.logsafe import RedactingFilter, RedactingFormatter

PRIV = "/data/data/com.whatsapp"
SHARED = "/sdcard/Android/media/com.whatsapp/WhatsApp"


def _cfg(tmp: Path, **kw: object) -> IngestConfig:
    return IngestConfig(out_dir=tmp / "out", kdf_overrides=FAST_KDF, **kw)  # type: ignore[arg-type]


def _pass() -> bytearray:
    return bytearray(PASSPHRASE.encode())


def _open(out: Path):  # type: ignore[no-untyped-def]
    master = derive_master(PASSPHRASE.encode(), read_params(out / "archive.kdf.json"))
    return SQLCipherProvider().open(out / "archive.db", subkey(master, "db"), read_only=True)


def _tmp_leftovers() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("waarchive-*")}


@pytest.fixture
def rooted_fs(mock: dict[str, Path], device_fs: dict[str, bytes]) -> dict[str, bytes]:
    fs = dict(device_fs)
    fs[f"{PRIV}/files/key"] = gen.make_key_file_14()
    fs[f"{PRIV}/databases/msgstore.db"] = mock["msgstore_plain"].read_bytes()
    fs[f"{PRIV}/databases/wa.db"] = mock["wa_plain"].read_bytes()
    return fs


def test_rooted_extraction(tmp_path: Path, rooted_fs: dict[str, bytes]) -> None:
    before = _tmp_leftovers()
    runner = FakeADBRunner(rooted=True, fs=rooted_fs)
    ui = ScriptedUI()
    res = Pipeline(ADBClient(runner), ui, SQLCipherProvider(), _cfg(tmp_path)).run(_pass())
    assert (
        res.rooted
        and res.stats.messages == len(gen.MODERN_MESSAGES)
        and res.stats.media_stored == 3
    )
    assert not ui.alerts  # no unrooted alert
    db = _open(res.archive.parent)
    assert db.execute("SELECT display_name FROM contact WHERE jid=?", (gen.ALICE,)).fetchone() == (
        "Alice Example",
    )
    assert _tmp_leftovers() == before  # plaintext artifacts wiped
    # private files were fetched through `su -c cat` with validated paths only
    assert any(a[2:3] == ["exec-out"] for a in runner.log if len(a) > 2)


def test_unrooted_alert_and_key_entry(tmp_path: Path, device_fs: dict[str, bytes]) -> None:
    runner = FakeADBRunner(rooted=False, fs=device_fs)
    ui = ScriptedUI(answers=["1"], secrets=[gen.ROOT_KEY_HEX])
    res = Pipeline(ADBClient(runner), ui, SQLCipherProvider(), _cfg(tmp_path)).run(_pass())
    assert not res.rooted
    alert = "\n".join(ui.alerts)
    for needle in (
        "NOT ROOTED",
        "sandbox",
        "FACTORY WIPE",
        "64-digit",
        "will NOT attempt exploits",
    ):
        assert needle in alert
    # never touched the private partition when unrooted
    assert not any("/data/data" in " ".join(a) for a in runner.log)
    assert not any("exec-out" in a for a in runner.log)
    assert res.stats.messages == len(gen.MODERN_MESSAGES) and res.stats.media_stored == 3


def test_unrooted_bad_key_then_good_key(tmp_path: Path, device_fs: dict[str, bytes]) -> None:
    ui = ScriptedUI(answers=["1"], secrets=["not-hex", "ab" * 31, gen.ROOT_KEY_HEX])
    res = Pipeline(
        ADBClient(FakeADBRunner(fs=device_fs)), ui, SQLCipherProvider(), _cfg(tmp_path)
    ).run(_pass())
    assert res.stats.messages > 0 and sum("Invalid key" in a for a in ui.alerts) == 2


def test_unrooted_three_bad_keys_abort(tmp_path: Path, device_fs: dict[str, bytes]) -> None:
    ui = ScriptedUI(answers=["1"], secrets=["x", "y", "z"])
    with pytest.raises(UsageError):
        Pipeline(
            ADBClient(FakeADBRunner(fs=device_fs)), ui, SQLCipherProvider(), _cfg(tmp_path)
        ).run(_pass())
    assert not (tmp_path / "out" / "archive.db").exists()


def test_unrooted_wrong_but_valid_key(tmp_path: Path, device_fs: dict[str, bytes]) -> None:
    ui = ScriptedUI(answers=["1"], secrets=["11" * 32])
    with pytest.raises(DecryptFailure, match="decryption failed"):
        Pipeline(
            ADBClient(FakeADBRunner(fs=device_fs)), ui, SQLCipherProvider(), _cfg(tmp_path)
        ).run(_pass())
    assert not (tmp_path / "out" / "archive.db").exists()


def test_unrooted_bundle_with_key_file(
    tmp_path: Path, device_fs: dict[str, bytes], mock: dict[str, Path]
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "key").write_bytes(gen.make_key_file_14())
    ui = ScriptedUI(answers=["2", str(bundle)])
    # crypt15 file + 158-byte key file: key candidate [126:158] is the root key
    res = Pipeline(
        ADBClient(FakeADBRunner(fs=device_fs)), ui, SQLCipherProvider(), _cfg(tmp_path)
    ).run(_pass())
    assert res.stats.messages == len(gen.MODERN_MESSAGES)


def test_bundle_with_plain_databases_offline(tmp_path: Path, mock: dict[str, Path]) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "msgstore.db").write_bytes(mock["msgstore_plain"].read_bytes())
    (bundle / "wa.db").write_bytes(mock["wa_plain"].read_bytes())
    res = Pipeline(None, ScriptedUI(), SQLCipherProvider(), _cfg(tmp_path, bundle=bundle)).run(
        _pass()
    )
    assert res.stats.messages == len(gen.MODERN_MESSAGES) and res.stats.media_stored == 0


def test_bundle_errors(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(UsageError):
        Pipeline(None, ScriptedUI(), SQLCipherProvider(), _cfg(tmp_path, bundle=empty)).run(_pass())
    with pytest.raises(UsageError):
        Pipeline(
            None, ScriptedUI(), SQLCipherProvider(), _cfg(tmp_path, bundle=tmp_path / "nope")
        ).run(_pass())


def test_bundle_symlinks_ignored(tmp_path: Path, mock: dict[str, Path]) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "msgstore.db").symlink_to(mock["msgstore_plain"])
    with pytest.raises(UsageError):
        Pipeline(None, ScriptedUI(), SQLCipherProvider(), _cfg(tmp_path, bundle=bundle)).run(
            _pass()
        )


@pytest.mark.parametrize(
    "devices,msg",
    [
        ([], "no Android device"),
        ([(SERIAL, "unauthorized")], "unauthorized"),
        ([(SERIAL, "offline")], "not ready"),
    ],
)
def test_device_failures(tmp_path: Path, devices: list[tuple[str, str]], msg: str) -> None:
    with pytest.raises(DeviceFailure, match=msg):
        Pipeline(
            ADBClient(FakeADBRunner(devices=devices)),
            ScriptedUI(),
            SQLCipherProvider(),
            _cfg(tmp_path),
        ).run(_pass())


def test_no_whatsapp_data_on_unrooted_device(tmp_path: Path) -> None:
    ui = ScriptedUI(answers=["1"], secrets=[gen.ROOT_KEY_HEX])
    with pytest.raises(DecryptFailure):
        Pipeline(ADBClient(FakeADBRunner()), ui, SQLCipherProvider(), _cfg(tmp_path)).run(_pass())


def test_unrooted_no_contacts_backup_uses_phone_numbers(
    tmp_path: Path, device_fs: dict[str, bytes]
) -> None:
    fs = {k: v for k, v in device_fs.items() if "wa.db" not in k}
    ui = ScriptedUI(answers=["1"], secrets=[gen.ROOT_KEY_HEX])
    res = Pipeline(ADBClient(FakeADBRunner(fs=fs)), ui, SQLCipherProvider(), _cfg(tmp_path)).run(
        _pass()
    )
    db = _open(res.archive.parent)
    assert db.execute("SELECT phone, source FROM contact WHERE jid=?", (gen.ALICE,)).fetchone() == (
        "+15550100101",
        "derived",
    )
    assert any("phone numbers" in s for s in ui.said)


def test_tempdir_wiped_after_failure(tmp_path: Path, device_fs: dict[str, bytes]) -> None:
    before = _tmp_leftovers()
    ui = ScriptedUI(answers=["1"], secrets=["22" * 32])
    with pytest.raises(DecryptFailure):
        Pipeline(
            ADBClient(FakeADBRunner(fs=device_fs)), ui, SQLCipherProvider(), _cfg(tmp_path)
        ).run(_pass())
    assert _tmp_leftovers() == before


def test_refuses_to_overwrite_existing_archive(tmp_path: Path, mock: dict[str, Path]) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "archive.db").write_bytes(b"precious")
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / "msgstore.db").write_bytes(mock["msgstore_plain"].read_bytes())
    with pytest.raises(UsageError):
        Pipeline(None, ScriptedUI(), SQLCipherProvider(), _cfg(tmp_path, bundle=bundle)).run(
            _pass()
        )
    assert (out / "archive.db").read_bytes() == b"precious"


def test_passphrase_zeroized_and_weak_rejected(tmp_path: Path, mock: dict[str, Path]) -> None:
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / "msgstore.db").write_bytes(mock["msgstore_plain"].read_bytes())
    pw = _pass()
    Pipeline(None, ScriptedUI(), SQLCipherProvider(), _cfg(tmp_path, bundle=bundle)).run(pw)
    assert pw == bytearray(len(pw))
    from waarchive.keys import KeyError_

    with pytest.raises(KeyError_):
        Pipeline(
            None,
            ScriptedUI(),
            SQLCipherProvider(),
            IngestConfig(tmp_path / "o2", bundle=bundle, kdf_overrides=FAST_KDF),
        ).run(bytearray(b"short"))


def test_logs_contain_no_pii_or_secrets(tmp_path: Path, rooted_fs: dict[str, bytes]) -> None:
    lines: list[str] = []

    class H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    h = H()
    h.setFormatter(RedactingFormatter("%(name)s %(message)s"))
    h.addFilter(RedactingFilter())
    root = logging.getLogger()
    old = root.level
    root.addHandler(h)
    root.setLevel(logging.DEBUG)
    try:
        Pipeline(
            ADBClient(FakeADBRunner(rooted=True, fs=rooted_fs)),
            ScriptedUI(),
            SQLCipherProvider(),
            _cfg(tmp_path),
        ).run(_pass())
    finally:
        root.removeHandler(h)
        root.setLevel(old)
    blob = "\n".join(lines)
    assert blob  # something was logged
    for leak in (
        gen.CANARY,
        "Alice",
        "15550100101",
        gen.ROOT_KEY_HEX,
        PASSPHRASE,
        "IMG-0001",
        "report.pdf",
    ):
        assert leak not in blob
