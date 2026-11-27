"""Real server for Playwright: synthetic archive (incl. a 100,000-message chat) + built SPA.

Usage: python tests/e2e_server.py <port> <web-dist-dir>
All data is synthetic. Credentials are fixed test values and never used outside this script.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "src")]

import uvicorn  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402

from archive_factory import FAST_KDF, PASSPHRASE  # noqa: E402
from fixtures import generate_mock_whatsapp as gen  # noqa: E402
from waarchive.ingest.archive import SQLCipherProvider  # noqa: E402
from waarchive.ingest.normalize import Normalizer, open_source_ro  # noqa: E402
from waarchive.keys import KdfParams, derive_master, subkey, write_params  # noqa: E402
from waarchive.media_vault import MediaVault  # noqa: E402
from waarchive.server.app import create_app  # noqa: E402
from waarchive.server.settings import Settings  # noqa: E402

PASSWORD = "e2e-Password-12345"
TOTP_SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
BIG_CHAT_MESSAGES = 100_000
BIG_JID = "15550100199@s.whatsapp.net"


def tiny_png() -> bytes:
    """A real 8x8 PNG (stdlib only) so the lightbox has something decodable to show."""
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    rows = b"".join(b"\x00" + bytes([0, 168, 132] * 8) for _ in range(8))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def add_photo(paths: dict[str, Path]) -> None:
    rel = "Media/WhatsApp Images/IMG-0002.png"
    (paths["media"] / rel).write_bytes(tiny_png())
    c = sqlite3.connect(paths["msgstore_plain"])
    c.execute(
        "INSERT INTO message VALUES(18, 1, 0, 'KEY0018', 1, 0, 1700001000000, 1, 'real photo')"
    )
    c.execute("INSERT INTO message_media VALUES(18, ?, 'image/png', 100, NULL, 8, 8)", (rel,))
    c.commit()
    c.close()


def add_big_chat(msgstore: Path) -> None:
    c = sqlite3.connect(msgstore)
    c.execute("INSERT INTO jid VALUES(9, ?, '15550100199', 's.whatsapp.net')", (BIG_JID,))
    c.execute("INSERT INTO chat VALUES(9, 9, NULL, 0, 0)")
    base = 1_690_000_000_000
    rows = [
        (100_000 + i, 9, i % 3 == 0, f"BIG{i}", None if i % 3 == 0 else 9, 13 if i % 3 == 0 else 0,
         base + i * 600_000, 0, f"bulk message number {i} " + ("with some extra words " * (i % 4)))
        for i in range(BIG_CHAT_MESSAGES)
    ]  # fmt: skip
    c.executemany(
        "INSERT INTO message VALUES(?,?,?,?,?,?,?,?,?)",
        [(a, b, int(cc), d, e, f, g, h, i) for a, b, cc, d, e, f, g, h, i in rows],
    )
    c.commit()
    c.close()


def build_archive(tmp: Path) -> Path:
    paths = gen.generate_all(tmp / "mock")
    add_photo(paths)
    add_big_chat(paths["msgstore_plain"])
    out = tmp / "archive"
    out.mkdir(mode=0o700)
    params = KdfParams.fresh(**FAST_KDF)
    write_params(out / "archive.kdf.json", params)
    master = derive_master(PASSPHRASE.encode(), params)
    dst = SQLCipherProvider().create(out / "archive.db", subkey(master, "db"))
    vault = MediaVault(out / "media", subkey(master, "media"), subkey(master, "media-name"))
    src, wa = open_source_ro(paths["msgstore_plain"]), open_source_ro(paths["wa_plain"])
    Normalizer(src, dst, wa=wa, media_root=paths["media"], vault=vault).run()
    for conn in (src, wa, dst):
        conn.close()
    return out


def main() -> None:
    port, dist = int(sys.argv[1]), Path(sys.argv[2])
    tmp = Path(tempfile.mkdtemp(prefix="wa-e2e-"))
    archive = build_archive(tmp)
    settings = Settings(
        archive_dir=archive, auth_mode="password_totp", base_url=f"http://localhost:{port}", port=port,
        password_hash=PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD),
        totp_secret=TOTP_SECRET, static_dir=dist,
    )  # fmt: skip
    print("E2E server ready", flush=True)
    uvicorn.run(
        create_app(settings), host="127.0.0.1", port=port, access_log=False, log_level="warning"
    )


if __name__ == "__main__":
    main()
