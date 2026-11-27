"""Build a real SQLCipher archive (same code path as the ingest CLI) for server tests."""

from __future__ import annotations

from pathlib import Path

from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest.archive import SQLCipherProvider
from waarchive.ingest.normalize import Normalizer, open_source_ro
from waarchive.keys import KdfParams, derive_master, subkey, write_params
from waarchive.media_vault import MediaVault

FAST_KDF = {"time_cost": 1, "memory_kib": 8, "parallelism": 1}
PASSPHRASE = "correct horse battery staple"


def make_archive(tmp: Path) -> Path:
    paths = gen.generate_all(tmp / "mock")
    out = tmp / "archive"
    out.mkdir(mode=0o700)
    params = KdfParams.fresh(**FAST_KDF)
    write_params(out / "archive.kdf.json", params)
    master = derive_master(PASSPHRASE.encode(), params)
    dst = SQLCipherProvider().create(out / "archive.db", subkey(master, "db"))
    vault = MediaVault(out / "media", subkey(master, "media"), subkey(master, "media-name"))
    src, wa = open_source_ro(paths["msgstore_plain"]), open_source_ro(paths["wa_plain"])
    Normalizer(src, dst, wa=wa, media_root=paths["media"], vault=vault).run()
    for c in (src, wa, dst):
        c.close()
    return out
