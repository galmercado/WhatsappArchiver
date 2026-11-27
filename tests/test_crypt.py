from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest import crypt
from waarchive.ingest.crypt import DecryptError, decrypt_backup


@pytest.fixture
def plain(tmp_path: Path) -> bytes:
    p = tmp_path / "p.db"
    gen.build_msgstore(p)
    return p.read_bytes()


def _write(tmp: Path, name: str, data: bytes) -> Path:
    p = tmp / name
    p.write_bytes(data)
    return p


@pytest.mark.parametrize("kind", [14, 15])
@pytest.mark.parametrize("md5", [False, True])
def test_roundtrip(tmp_path: Path, plain: bytes, kind: int, md5: bool) -> None:
    src = _write(tmp_path, f"m.db.crypt{kind}", gen.encrypt_backup(plain, kind, md5_trailer=md5))
    out = tmp_path / "out.db"
    decrypt_backup(src, out, [bytearray(gen.ROOT_KEY)])
    assert out.read_bytes() == plain
    assert (out.stat().st_mode & 0o777) == 0o600


def test_wrong_key_fails_and_leaves_no_output(tmp_path: Path, plain: bytes) -> None:
    src = _write(tmp_path, "m.db.crypt15", gen.encrypt_backup(plain, 15))
    out = tmp_path / "out.db"
    with pytest.raises(DecryptError):
        decrypt_backup(src, out, [bytearray(b"\x01" * 32)])
    assert not out.exists()


def test_candidate_list_finds_right_key(tmp_path: Path, plain: bytes) -> None:
    src = _write(tmp_path, "m.db.crypt15", gen.encrypt_backup(plain, 15))
    out = tmp_path / "out.db"
    decrypt_backup(src, out, [bytearray(b"\x02" * 32), bytearray(gen.ROOT_KEY)])
    assert out.read_bytes() == plain


def test_tampered_ciphertext_rejected(tmp_path: Path, plain: bytes) -> None:
    blob = bytearray(gen.encrypt_backup(plain, 15))
    blob[len(blob) // 2] ^= 0x01
    src = _write(tmp_path, "m.db.crypt15", bytes(blob))
    out = tmp_path / "out.db"
    with pytest.raises(DecryptError):
        decrypt_backup(src, out, [bytearray(gen.ROOT_KEY)])
    assert not out.exists()


def test_tampered_tag_rejected(tmp_path: Path, plain: bytes) -> None:
    blob = bytearray(gen.encrypt_backup(plain, 15))
    blob[-1] ^= 0xFF
    src = _write(tmp_path, "m.db.crypt15", bytes(blob))
    with pytest.raises(DecryptError):
        decrypt_backup(src, tmp_path / "o", [bytearray(gen.ROOT_KEY)])


def test_truncated_file_rejected(tmp_path: Path, plain: bytes) -> None:
    blob = gen.encrypt_backup(plain, 15)
    for cut in (3, 10, 40, len(blob) // 2, len(blob) - 20):
        src = _write(tmp_path, "m.db.crypt15", blob[:cut])
        with pytest.raises(DecryptError):
            decrypt_backup(src, tmp_path / "o", [bytearray(gen.ROOT_KEY)])


@pytest.mark.parametrize(
    "head", [b"\x00\x01", b"\xff\x01" + b"\x00" * 10, b"\x05\x01\xff\xff\xff\xff\xff\xff"]
)
def test_malformed_headers(tmp_path: Path, head: bytes) -> None:
    src = _write(tmp_path, "m.db.crypt15", head + b"\x00" * 100)
    with pytest.raises(DecryptError):
        decrypt_backup(src, tmp_path / "o", [bytearray(gen.ROOT_KEY)])


def test_unsupported_extension(tmp_path: Path) -> None:
    src = _write(tmp_path, "m.db.crypt12", b"x" * 100)
    with pytest.raises(DecryptError):
        decrypt_backup(src, tmp_path / "o", [bytearray(gen.ROOT_KEY)])


def test_non_sqlite_payload_rejected(tmp_path: Path) -> None:
    src = _write(tmp_path, "m.db.crypt15", gen.encrypt_backup(b"not a database" * 10, 15))
    with pytest.raises(DecryptError):
        decrypt_backup(src, tmp_path / "o", [bytearray(gen.ROOT_KEY)])


def test_decompression_bomb_capped(tmp_path: Path) -> None:
    bomb = b"SQLite format 3\x00" + bytes(5_000_000)
    src = _write(tmp_path, "m.db.crypt15", gen.encrypt_backup(bomb, 15))
    out = tmp_path / "o"
    with pytest.raises(DecryptError):
        decrypt_backup(src, out, [bytearray(gen.ROOT_KEY)], max_output=100_000)
    assert not out.exists()
    assert len(zlib.compress(bomb)) < 20_000  # sanity: it really is a bomb


def test_parse_hex_key_variants() -> None:
    k = crypt.parse_hex_key(gen.ROOT_KEY_HEX)
    assert bytes(k) == gen.ROOT_KEY
    spaced = " ".join(gen.ROOT_KEY_HEX[i : i + 4] for i in range(0, 64, 4))
    assert bytes(crypt.parse_hex_key(spaced)) == gen.ROOT_KEY
    for bad in ("", "zz" * 32, "ab" * 31, "ab" * 33, gen.ROOT_KEY_HEX + "0"):
        with pytest.raises(DecryptError):
            crypt.parse_hex_key(bad)


def test_key_file_candidates() -> None:
    assert bytes(crypt.key_candidates_from_file(gen.make_key_file_14())[0]) == gen.ROOT_KEY
    assert bytes(crypt.key_candidates_from_file(gen.ROOT_KEY)[0]) == gen.ROOT_KEY
    with pytest.raises(DecryptError):
        crypt.key_candidates_from_file(b"short")


def test_crypt15_derivation_deterministic_and_distinct() -> None:
    a = crypt.derive_crypt15_key(gen.ROOT_KEY)
    assert a == crypt.derive_crypt15_key(gen.ROOT_KEY) and a != gen.ROOT_KEY and len(a) == 32
