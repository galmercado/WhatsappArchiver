"""Encrypted media store.

Each media file is stored as ``MAGIC || nonce(16) || AES-256-CTR(plaintext)`` under an
opaque HMAC-derived name, so neither filenames nor directory structure leak onto disk.
CTR gives cheap random access for HTTP Range requests. CTR is not authenticated; the
archive's DB (SQLCipher) holds the authoritative metadata and the vault directory should
also sit on a volume with normal OS permissions (0700).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .secure_fs import open_private

MAGIC = b"WAM1"
HEADER_LEN = len(MAGIC) + 16
_BLOCK = 16
_CHUNK = 1 << 16


class MediaPathError(Exception):
    pass


class VaultClosedError(Exception):
    pass


def validate_rel_path(rel: str) -> str:
    """Reject anything that is not a clean, relative, forward-slash path."""
    if not rel or len(rel) > 1024 or "\x00" in rel or "\\" in rel:
        raise MediaPathError("invalid media path")
    p = PurePosixPath(rel)
    if p.is_absolute() or any(part in ("..", "") for part in rel.split("/")):
        raise MediaPathError("invalid media path")
    return str(p)


def safe_join(root: Path, rel: str) -> Path:
    """Resolve *rel* under *root*; refuse traversal, absolute paths and symlinks."""
    clean = validate_rel_path(rel)
    base = root.resolve()
    candidate = base / clean
    cur = base
    for part in PurePosixPath(clean).parts:
        cur = cur / part
        if cur.is_symlink():
            raise MediaPathError("symlinks are not allowed")
    resolved = candidate.resolve()
    if not resolved.is_relative_to(base):
        raise MediaPathError("path escapes media root")
    return resolved


def _ctr(key: bytes, nonce: bytes, offset: int) -> Cipher[modes.CTR]:
    counter = (int.from_bytes(nonce, "big") + offset // _BLOCK) % (1 << 128)
    return Cipher(algorithms.AES(key), modes.CTR(counter.to_bytes(16, "big")))


class MediaVault:
    def __init__(self, root: Path, key: bytes, name_key: bytes) -> None:
        if len(key) != 32 or len(name_key) != 32:
            raise ValueError("vault keys must be 32 bytes")
        self._root = root
        self._key: bytes | None = key
        self._name_key: bytes | None = name_key
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def close(self) -> None:
        """Drop key references; in-flight readers stop at their next chunk."""
        self._key = None
        self._name_key = None

    def _keys(self) -> tuple[bytes, bytes]:
        if self._key is None or self._name_key is None:
            raise VaultClosedError("media vault is locked")
        return self._key, self._name_key

    def blob_path(self, rel: str) -> Path:
        clean = validate_rel_path(rel)
        h = hmac.new(self._keys()[1], clean.encode("utf-8"), hashlib.sha256).hexdigest()
        return self._root / h[:2] / h[2:]

    def store(self, rel: str, src: Path) -> int:
        """Encrypt *src* into the vault. Returns plaintext size."""
        dest = self.blob_path(rel)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        nonce = secrets.token_bytes(16)
        enc = _ctr(self._keys()[0], nonce, 0).encryptor()
        size = 0
        with src.open("rb") as fin, open_private(dest) as fout:
            fout.write(MAGIC + nonce)
            while chunk := fin.read(_CHUNK):
                fout.write(enc.update(chunk))
                size += len(chunk)
            fout.write(enc.finalize())
        return size

    def size(self, rel: str) -> int:
        path = self.blob_path(rel)
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError("media not found")
        return path.stat().st_size - HEADER_LEN

    def read_range(self, rel: str, start: int, end: int) -> Iterator[bytes]:
        """Yield plaintext bytes [start, end] inclusive."""
        total = self.size(rel)
        if start < 0 or end < start or start >= total:
            raise ValueError("unsatisfiable range")
        end = min(end, total - 1)
        path = self.blob_path(rel)
        with path.open("rb") as fh:
            head = fh.read(HEADER_LEN)
            if head[: len(MAGIC)] != MAGIC:
                raise ValueError("corrupt media blob")
            nonce = head[len(MAGIC) :]
            aligned = start - (start % _BLOCK)
            dec = _ctr(self._keys()[0], nonce, aligned).decryptor()
            fh.seek(HEADER_LEN + aligned)
            skip = start - aligned
            remaining = end - start + 1
            while remaining > 0:
                self._keys()  # stop mid-stream if the vault was locked
                raw = fh.read(min(_CHUNK, remaining + skip))
                if not raw:
                    break
                plain = dec.update(raw)
                if skip:
                    plain, skip = plain[skip:], 0
                plain = plain[:remaining]
                remaining -= len(plain)
                if plain:
                    yield plain

    def read_all(self, rel: str) -> bytes:
        return (
            b"".join(self.read_range(rel, 0, max(self.size(rel) - 1, 0))) if self.size(rel) else b""
        )


def chmod_private_dir(path: Path) -> None:
    os.chmod(path, 0o700)
