from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest

from conftest import FAST_KDF, PASSPHRASE
from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest.archive import SQLCipherProvider, WrongKeyError
from waarchive.ingest.normalize import Normalizer, SchemaError, open_source_ro
from waarchive.keys import KdfParams, derive_master, subkey
from waarchive.media_vault import MediaVault

KEY = b"\x07" * 32


def _build(tmp: Path, schema: str = "modern", *, wa: bool = True, media: bool = True):  # type: ignore[no-untyped-def]
    paths = gen.generate_all(tmp / "m", schema=schema)
    prov = SQLCipherProvider()
    dst = prov.create(tmp / "a.db", KEY)
    vault = MediaVault(tmp / "vault", b"k" * 32, b"n" * 32)
    src = open_source_ro(paths["msgstore_plain"])
    wac = open_source_ro(paths["wa_plain"]) if wa else None
    stats = Normalizer(
        src, dst, wa=wac, media_root=paths["media"] if media else None, vault=vault
    ).run()
    return dst, stats, vault


def test_modern_schema(tmp_path: Path) -> None:
    db, stats, _ = _build(tmp_path)
    assert (
        stats.schema == "modern" and stats.chats == 3 and stats.messages == len(gen.MODERN_MESSAGES)
    )
    q = lambda s, *a: db.execute(s, a).fetchall()
    assert q("SELECT display_name, phone, source FROM contact WHERE jid=?", gen.ALICE) == [
        ("Alice Example", "+1 555 0100 101", "wa.db")
    ]
    assert q("SELECT is_group, display_name FROM contact WHERE jid=?", gen.GROUP) == [
        (1, "Test Group")
    ]
    # type refinement + media
    assert q("SELECT type FROM message WHERE id=13") == [("ptt",)]
    assert q("SELECT type FROM message WHERE id=12") == [("image",)]
    # from_me ticks: status mapped; incoming has none
    assert q("SELECT status FROM message WHERE id=2") == [(3,)]
    assert q("SELECT status FROM message WHERE id=1") == [(None,)]
    # quoted reply
    assert q("SELECT quoted_id FROM message WHERE id=15") == [(1,)]
    assert q("SELECT quoted_text FROM message_quoted WHERE message_id=15") == [
        ("Hello from Alice",)
    ]
    # system event with target
    assert q("SELECT type, system_kind, system_target_jid FROM message WHERE id=23") == [
        ("system", "added", gen.CAROL)
    ]
    # group participants (distinct senders only, never me)
    assert {r[0] for r in q("SELECT jid FROM participant WHERE chat_id=2")} == {gen.ALICE, gen.BOB}
    # last_message_ts populated
    assert q("SELECT last_message_ts FROM chat WHERE id=1") == [(1_700_000_960_000,)]


def test_payloads_stored_verbatim_except_nul(tmp_path: Path) -> None:
    db, _, _ = _build(tmp_path)
    get = lambda i: db.execute("SELECT text FROM message WHERE id=?", (i,)).fetchone()[0]
    assert get(3) == gen.XSS and get(4) == gen.XSS_IMG and get(5) == gen.JS_URL
    assert (
        get(6) == gen.SQLI and get(7) == gen.FTS_EVIL and get(8) == gen.EMOJI and get(9) == gen.RTL
    )
    assert get(10) == "ab nul"
    assert db.execute("SELECT count(*) FROM message").fetchone()[0] == len(
        gen.MODERN_MESSAGES
    )  # SQLi harmless


def test_hostile_media_paths_not_ingested(tmp_path: Path) -> None:
    db, stats, vault = _build(tmp_path)
    assert stats.media_stored == 3
    rows = dict(db.execute("SELECT message_id, stored FROM message_media").fetchall())
    assert rows[12] == rows[13] == rows[14] == 1 and rows[16] == rows[17] == 0
    assert db.execute(
        "SELECT rel_path FROM message_media WHERE message_id IN (16,17)"
    ).fetchall() == [(None,), (None,)]
    assert vault.read_all("Media/WhatsApp Images/IMG-0001.jpg").startswith(b"\xff\xd8\xff\xe0")


def test_fts_search(tmp_path: Path) -> None:
    db, _, _ = _build(tmp_path)
    hits = db.execute(
        "SELECT rowid FROM message_fts WHERE message_fts MATCH ?", ('"group"',)
    ).fetchall()
    assert {h[0] for h in hits} == {20, 21, 22}
    assert db.execute(
        "SELECT rowid FROM message_fts WHERE message_fts MATCH ?", ("thumbs",)
    ).fetchall() == [(8,)]


def test_without_wa_db_falls_back_to_phone_numbers(tmp_path: Path) -> None:
    db, stats, _ = _build(tmp_path, wa=False)
    assert db.execute(
        "SELECT display_name, phone, source FROM contact WHERE jid=?", (gen.ALICE,)
    ).fetchone() == (None, "+15550100101", "derived")
    assert stats.contacts >= 4


def test_legacy_schema(tmp_path: Path) -> None:
    db, stats, _ = _build(tmp_path, "legacy")
    assert stats.schema == "legacy" and stats.chats == 2 and stats.messages == 4
    assert db.execute("SELECT subject FROM chat WHERE jid=?", (gen.GROUP,)).fetchone() == (
        "Legacy Group",
    )
    assert db.execute("SELECT quoted_id FROM message WHERE id=2").fetchone() == (1,)
    assert db.execute("SELECT stored FROM message_media WHERE message_id=3").fetchone() == (
        1,
    )  # basename lookup
    assert db.execute("SELECT sender_jid FROM message WHERE id=4").fetchone() == (gen.BOB,)


def test_minimal_schema_missing_optional_columns(tmp_path: Path) -> None:
    db, stats, _ = _build(tmp_path, "minimal", wa=False, media=False)
    assert stats.messages == 2 and stats.chats == 1
    assert db.execute("SELECT type, text, from_me FROM message ORDER BY id").fetchall() == [
        ("text", None, 0),
        ("text", None, 1),
    ]


def test_unknown_schema_rejected(tmp_path: Path) -> None:
    p = tmp_path / "x.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE foo(a)")
    c.commit()
    c.close()
    dst = SQLCipherProvider().create(tmp_path / "a.db", KEY)
    with pytest.raises(SchemaError):
        Normalizer(open_source_ro(p), dst).run()


def test_sqlcipher_encryption_at_rest(tmp_path: Path) -> None:
    db, _, _ = _build(tmp_path)
    db.close()
    raw = (tmp_path / "a.db").read_bytes()
    assert not raw.startswith(b"SQLite format 3")
    assert gen.CANARY.encode() not in raw and b"Alice Example" not in raw
    assert stat.S_IMODE((tmp_path / "a.db").stat().st_mode) == 0o600
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(tmp_path / "a.db").execute("select * from sqlite_master").fetchall()
    prov = SQLCipherProvider()
    with pytest.raises(WrongKeyError):
        prov.open(tmp_path / "a.db", b"\x08" * 32)
    ok = prov.open(tmp_path / "a.db", KEY, read_only=True)
    assert ok.execute("SELECT count(*) FROM message").fetchone()[0] > 0


def test_create_refuses_overwrite(tmp_path: Path) -> None:
    prov = SQLCipherProvider()
    prov.create(tmp_path / "a.db", KEY).close()
    with pytest.raises(FileExistsError):
        prov.create(tmp_path / "a.db", KEY)


def test_kdf_and_subkeys() -> None:
    p = KdfParams.fresh(**FAST_KDF)
    m1, m2 = derive_master(PASSPHRASE.encode(), p), derive_master(PASSPHRASE.encode(), p)
    assert m1 == m2 and subkey(m1, "db") != subkey(m1, "media") and len(subkey(m1, "db")) == 32
    assert derive_master(PASSPHRASE.encode(), KdfParams.fresh(**FAST_KDF)) != m1
    assert KdfParams.from_json(p.to_json()) == p
    from waarchive.keys import KeyError_

    with pytest.raises(KeyError_):
        derive_master(b"short", p)
    with pytest.raises(KeyError_):
        KdfParams.from_json('{"v":1,"salt":"AAAA","t":1,"m":8,"p":1}')
