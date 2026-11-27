from __future__ import annotations

import os
import secrets
from pathlib import Path

import pytest

from waarchive.media_vault import MediaPathError, MediaVault, safe_join, validate_rel_path


@pytest.fixture
def vault(tmp_path: Path) -> MediaVault:
    return MediaVault(tmp_path / "v", b"k" * 32, b"n" * 32)


@pytest.fixture
def src(tmp_path: Path) -> Path:
    p = tmp_path / "src.bin"
    p.write_bytes(secrets.token_bytes(100_003))
    return p


def test_roundtrip_and_ciphertext_differs(vault: MediaVault, src: Path) -> None:
    vault.store("Media/a.jpg", src)
    assert vault.read_all("Media/a.jpg") == src.read_bytes()
    blob = vault.blob_path("Media/a.jpg").read_bytes()
    assert src.read_bytes()[:64] not in blob


def test_no_filename_leak_and_private_mode(vault: MediaVault, src: Path, tmp_path: Path) -> None:
    vault.store("Media/WhatsApp Images/secret-name.jpg", src)
    names = [p.name for p in (tmp_path / "v").rglob("*")]
    assert not any("secret" in n or "jpg" in n for n in names)
    assert (
        vault.blob_path("Media/WhatsApp Images/secret-name.jpg").stat().st_mode & 0o777
    ) == 0o600


@pytest.mark.parametrize(
    "start,end",
    [(0, 0), (0, 15), (15, 16), (16, 31), (1, 100_002), (99_990, 100_002), (12345, 54321)],
)
def test_ranges_match_plaintext(vault: MediaVault, src: Path, start: int, end: int) -> None:
    vault.store("m.bin", src)
    data = src.read_bytes()
    assert b"".join(vault.read_range("m.bin", start, end)) == data[start : end + 1]


def test_range_clamped_and_invalid(vault: MediaVault, src: Path) -> None:
    vault.store("m.bin", src)
    data = src.read_bytes()
    assert b"".join(vault.read_range("m.bin", 100_000, 10**9)) == data[100_000:]
    for s, e in ((-1, 5), (5, 4), (len(data), len(data) + 5)):
        with pytest.raises(ValueError):
            list(vault.read_range("m.bin", s, e))


def test_wrong_key_yields_garbage(tmp_path: Path, vault: MediaVault, src: Path) -> None:
    vault.store("m.bin", src)
    other = MediaVault(tmp_path / "v", b"x" * 32, b"n" * 32)
    assert other.read_all("m.bin") != src.read_bytes()


def test_missing_media(vault: MediaVault) -> None:
    with pytest.raises(FileNotFoundError):
        vault.size("nope.bin")


@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "a/../../b",
        "a//b",
        "",
        "a\\b",
        "a\x00b",
        "..",
        "a/./..//b",
    ],
)
def test_rel_path_validation(bad: str) -> None:
    with pytest.raises(MediaPathError):
        validate_rel_path(bad)


def test_safe_join_blocks_traversal_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "ok.txt").write_text("x")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    os.symlink(outside, root / "link.txt")
    os.symlink(tmp_path, root / "dirlink")
    assert safe_join(root, "ok.txt").read_text() == "x"
    for bad in (
        "../outside.txt",
        "link.txt",
        "dirlink/outside.txt",
        "%2e%2e/outside.txt/..",
        "/etc/passwd",
    ):
        try:
            p = safe_join(root, bad)
        except MediaPathError:
            continue
        assert p.is_relative_to(root.resolve()), bad  # literal "%2e%2e" is just a harmless filename
