"""Synthetic, PII-free WhatsApp fixtures: databases, contacts, media and encrypted backups.

All names/numbers are fictitious (555-01xx range). Run directly to write a sample set:
    python tests/fixtures/generate_mock_whatsapp.py OUTDIR
"""

from __future__ import annotations

import hashlib
import hmac
import sqlite3
import sys
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT_KEY = bytes.fromhex("00112233445566778899aabbccddeeff" * 2)
ROOT_KEY_HEX = ROOT_KEY.hex()
IV = bytes(range(16))

ALICE = "15550100101@s.whatsapp.net"
BOB = "15550100102@s.whatsapp.net"
CAROL = "15550100103@s.whatsapp.net"
GROUP = "120363000000000001@g.us"

XSS = "<script>alert(1)</script>"
XSS_IMG = '<img src=x onerror="alert(document.cookie)">'
JS_URL = "javascript:alert(1)"
SQLI = "'); DROP TABLE message;--"
FTS_EVIL = '"unbalanced NEAR(a b) * OR AND -x'
EMOJI = "Family \U0001f468‍\U0001f469‍\U0001f467 thumbs \U0001f44d\U0001f3fd"
RTL = "مرحبا שלום"
LONG = "lorem " * 2000
CANARY = "CANARY-SECRET-PHRASE-7731"

# (id, chat, from_me, sender_jid_row, status, ts_ms, type, text)
MODERN_MESSAGES: list[tuple[int, int, int, int | None, int, int, int, str | None]] = [
    (1, 1, 0, 1, 0, 1_700_000_000_000, 0, "Hello from Alice " + CANARY),
    (2, 1, 1, None, 13, 1_700_000_060_000, 0, "Reply from me"),
    (3, 1, 0, 1, 0, 1_700_000_120_000, 0, XSS),
    (4, 1, 0, 1, 0, 1_700_000_180_000, 0, XSS_IMG),
    (5, 1, 0, 1, 0, 1_700_000_240_000, 0, JS_URL),
    (6, 1, 1, None, 5, 1_700_000_300_000, 0, SQLI),
    (7, 1, 0, 1, 0, 1_700_000_360_000, 0, FTS_EVIL),
    (8, 1, 0, 1, 0, 1_700_000_420_000, 0, EMOJI),
    (9, 1, 0, 1, 0, 1_700_000_480_000, 0, RTL),
    (10, 1, 0, 1, 0, 1_700_000_540_000, 0, "a\x00b nul"),
    (11, 1, 0, 1, 0, 1_700_000_600_000, 0, LONG),
    (12, 1, 0, 1, 0, 1_700_000_660_000, 1, "photo caption"),
    (13, 1, 0, 1, 0, 1_700_000_720_000, 2, None),
    (14, 1, 1, None, 4, 1_700_000_780_000, 9, "report.pdf"),
    (15, 1, 1, None, 13, 1_700_000_840_000, 0, "quoted reply to hello"),
    (16, 1, 0, 1, 0, 1_700_000_900_000, 1, "traversal attempt"),
    (17, 1, 0, 1, 0, 1_700_000_960_000, 1, "absolute path attempt"),
    (20, 2, 0, 1, 0, 1_700_001_000_000, 0, "group hi from alice"),
    (21, 2, 0, 2, 0, 1_700_001_060_000, 0, "group hi from bob"),
    (22, 2, 1, None, 5, 1_700_001_120_000, 0, "group hi from me"),
    (23, 2, 0, None, 0, 1_700_001_180_000, 7, None),
]


def build_msgstore(path: Path, schema: str = "modern") -> None:
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    try:
        {"modern": _modern, "legacy": _legacy, "minimal": _minimal}[schema](conn)
        conn.commit()
    finally:
        conn.close()


def _modern(c: sqlite3.Connection) -> None:
    c.executescript(
        """
CREATE TABLE jid(_id INTEGER PRIMARY KEY, raw_string TEXT, user TEXT, server TEXT);
CREATE TABLE chat(_id INTEGER PRIMARY KEY, jid_row_id INTEGER, subject TEXT, archived INTEGER, sort_timestamp INTEGER);
CREATE TABLE message(_id INTEGER PRIMARY KEY, chat_row_id INTEGER, from_me INTEGER, key_id TEXT,
  sender_jid_row_id INTEGER, status INTEGER, timestamp INTEGER, message_type INTEGER, text_data TEXT);
CREATE TABLE message_media(message_row_id INTEGER PRIMARY KEY, file_path TEXT, mime_type TEXT,
  file_size INTEGER, media_duration INTEGER, width INTEGER, height INTEGER);
CREATE TABLE message_quoted(message_row_id INTEGER PRIMARY KEY, parent_message_row_id INTEGER,
  key_id TEXT, text_data TEXT, sender_jid_row_id INTEGER, message_type INTEGER);
CREATE TABLE message_system(message_row_id INTEGER PRIMARY KEY, action_type INTEGER);
CREATE TABLE message_system_chat_participant(message_row_id INTEGER, user_jid_row_id INTEGER);
"""
    )
    jids = [(1, ALICE), (2, BOB), (3, CAROL), (4, GROUP)]
    c.executemany(
        "INSERT INTO jid VALUES(?,?,?,?)",
        [(i, j, j.split("@")[0], j.split("@")[1]) for i, j in jids],
    )
    c.executemany(
        "INSERT INTO chat VALUES(?,?,?,?,?)",
        [(1, 1, None, 0, 0), (2, 4, "Test Group", 0, 0), (3, 2, None, 1, 0)],
    )
    c.executemany(
        "INSERT INTO message VALUES(?,?,?,?,?,?,?,?,?)",
        [
            (i, ch, fm, f"KEY{i:04d}", sj, st, ts, ty, tx)
            for i, ch, fm, sj, st, ts, ty, tx in MODERN_MESSAGES
        ],
    )
    c.executemany(
        "INSERT INTO message_media VALUES(?,?,?,?,?,?,?)",
        [
            (12, "Media/WhatsApp Images/IMG-0001.jpg", "image/jpeg", 100, None, 64, 48),
            (
                13,
                "Media/WhatsApp Voice Notes/PTT-0001.opus",
                "audio/ogg; codecs=opus",
                40,
                3,
                None,
                None,
            ),
            (14, "Media/WhatsApp Documents/report.pdf", "application/pdf", 60, None, None, None),
            (16, "../../etc/passwd", "image/jpeg", 1, None, None, None),
            (17, "/etc/passwd", "image/jpeg", 1, None, None, None),
        ],
    )
    c.execute("INSERT INTO message_quoted VALUES(15, 1, 'KEY0001', 'Hello from Alice', 1, 0)")
    c.execute("INSERT INTO message_system VALUES(23, 12)")
    c.execute("INSERT INTO message_system_chat_participant VALUES(23, 3)")


def _legacy(c: sqlite3.Connection) -> None:
    c.executescript(
        """
CREATE TABLE messages(_id INTEGER PRIMARY KEY, key_remote_jid TEXT, key_from_me INTEGER, key_id TEXT,
  status INTEGER, data TEXT, timestamp INTEGER, media_wa_type INTEGER, media_mime_type TEXT,
  media_size INTEGER, media_name TEXT, media_duration INTEGER, remote_resource TEXT, quoted_row_id INTEGER);
CREATE TABLE chat_list(_id INTEGER PRIMARY KEY, key_remote_jid TEXT, subject TEXT);
"""
    )
    rows = [
        (
            1,
            ALICE,
            0,
            "L1",
            0,
            "legacy hello",
            1_600_000_000_000,
            0,
            None,
            None,
            None,
            None,
            None,
            0,
        ),
        (
            2,
            ALICE,
            1,
            "L2",
            13,
            "legacy reply",
            1_600_000_060_000,
            0,
            None,
            None,
            None,
            None,
            None,
            1,
        ),
        (
            3,
            ALICE,
            0,
            "L3",
            0,
            None,
            1_600_000_120_000,
            1,
            "image/jpeg",
            100,
            "IMG-0001.jpg",
            None,
            None,
            0,
        ),
        (
            4,
            GROUP,
            0,
            "L4",
            0,
            "legacy group",
            1_600_000_180_000,
            0,
            None,
            None,
            None,
            None,
            BOB,
            0,
        ),
    ]
    c.executemany("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    c.execute("INSERT INTO chat_list VALUES(1, ?, 'Legacy Group')", (GROUP,))


def _minimal(c: sqlite3.Connection) -> None:
    """Only the bare minimum columns: optional ones are absent."""
    c.executescript(
        """
CREATE TABLE jid(_id INTEGER PRIMARY KEY, raw_string TEXT);
CREATE TABLE chat(_id INTEGER PRIMARY KEY, jid_row_id INTEGER);
CREATE TABLE message(_id INTEGER PRIMARY KEY, chat_row_id INTEGER, from_me INTEGER, timestamp INTEGER);
"""
    )
    c.execute("INSERT INTO jid VALUES(1, ?)", (ALICE,))
    c.execute("INSERT INTO chat VALUES(1, 1)")
    c.executemany("INSERT INTO message VALUES(?,1,?,?)", [(1, 0, 1000), (2, 1, 2000)])


def build_wa_db(path: Path) -> None:
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE wa_contacts(_id INTEGER PRIMARY KEY, jid TEXT, display_name TEXT, wa_name TEXT, number TEXT)"
    )
    conn.executemany(
        "INSERT INTO wa_contacts(jid, display_name, wa_name, number) VALUES(?,?,?,?)",
        [
            (ALICE, "Alice Example", "alice", "+1 555 0100 101"),
            (BOB, "Bob Example", None, "+1 555 0100 102"),
            (CAROL, None, "carol-wa", None),
        ],
    )
    conn.commit()
    conn.close()


def build_media_tree(root: Path) -> None:
    files = {
        "Media/WhatsApp Images/IMG-0001.jpg": b"\xff\xd8\xff\xe0FAKEJPEG" + bytes(range(256)) * 2,
        "Media/WhatsApp Voice Notes/PTT-0001.opus": b"OggS" + bytes(range(36)),
        "Media/WhatsApp Documents/report.pdf": b"%PDF-1.4 fake " + b"x" * 46,
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


# ---------------------------------------------------------------- encrypted backups
def _proto_header(iv: bytes) -> bytes:
    """BackupPrefix-like protobuf: a varint field, a string field, and nested message with the IV."""
    inner = b"\x0a\x10" + iv  # field1 (bytes, 16) -> the IV
    return b"\x08\x01" + b"\x12\x03abc" + b"\x1a" + bytes([len(inner)]) + inner


def encrypt_backup(
    plain_db: bytes,
    kind: int = 15,
    root_key: bytes = ROOT_KEY,
    iv: bytes = IV,
    md5_trailer: bool = False,
) -> bytes:
    if kind == 15:
        priv = hmac.new(bytes(32), root_key, hashlib.sha256).digest()
        aes_key = hmac.new(priv, b"backup encryption\x01", hashlib.sha256).digest()
    else:
        aes_key = root_key
    ct_and_tag = AESGCM(aes_key).encrypt(iv, zlib.compress(plain_db), None)
    proto = _proto_header(iv)
    out = bytes([len(proto)]) + b"\x01" + proto + ct_and_tag
    if md5_trailer:
        out += hashlib.md5(out).digest()
    return out


def make_key_file_14(aes_key: bytes = ROOT_KEY) -> bytes:
    """158-byte device `key` file with the AES key at [126:158]."""
    return bytes(126) + aes_key


def generate_all(out: Path, *, kind: int = 15, schema: str = "modern") -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    ms, wa = out / "msgstore.db", out / "wa.db"
    build_msgstore(ms, schema)
    build_wa_db(wa)
    paths = {"msgstore_plain": ms, "wa_plain": wa}
    paths["msgstore_crypt"] = out / f"msgstore.db.crypt{kind}"
    paths["msgstore_crypt"].write_bytes(encrypt_backup(ms.read_bytes(), kind))
    paths["wa_crypt"] = out / f"wa.db.crypt{kind}"
    paths["wa_crypt"].write_bytes(encrypt_backup(wa.read_bytes(), kind, iv=bytes(range(16, 32))))
    build_media_tree(out / "media")
    paths["media"] = out / "media"
    (out / "key").write_bytes(make_key_file_14())
    paths["key"] = out / "key"
    return paths


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "mock_out")
    for k, v in generate_all(target).items():
        print(k, v)
    print("64-hex key:", ROOT_KEY_HEX)
