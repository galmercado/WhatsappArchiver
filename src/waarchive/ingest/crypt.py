"""WhatsApp .crypt14 / .crypt15 decryption (offline, streaming, authenticated).

Format assumptions (from public reverse-engineering; verify against a real backup of
your own before relying on this):

* byte 0   = protobuf header length, byte 1 = 0x01 flag (skipped when present)
* header   = protobuf; the 16-byte AES-GCM IV is located by walking the message
* payload  = AES-256-GCM(zlib(sqlite)); trailer is the 16-byte GCM tag, optionally
             followed by a 16-byte MD5. Both layouts are tried; GCM authentication
             decides which one is right, so a wrong guess can never pass silently.
* crypt15  = AES key derived from the 32-byte root key:
             HMAC(HMAC(0^32, root), b"backup encryption" || 0x01)
* crypt14  = AES key is the 32 bytes stored in the device `key` file
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import re
import zlib
from collections.abc import Callable
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from ..secure_fs import open_private

SQLITE_MAGIC = b"SQLite format 3\x00"
HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CHUNK = 1 << 20
DEFAULT_MAX_OUTPUT = 32 * 1024**3
MAX_HEADER = 255


class DecryptError(Exception):
    """Generic on purpose: never reveals which stage/candidate failed."""


# ---------------------------------------------------------------------------- keys
def parse_hex_key(text: str) -> bytearray:
    cleaned = re.sub(r"[\s-]", "", text)
    if not HEX_KEY_RE.fullmatch(cleaned):
        raise DecryptError("key must be exactly 64 hexadecimal characters")
    return bytearray(bytes.fromhex(cleaned))


def key_candidates_from_file(data: bytes) -> list[bytearray]:
    """Candidate 32-byte keys from a pulled `key` / `encrypted_backup.key` file."""
    out: list[bytearray] = []
    n = len(data)
    if n == 32:
        out.append(bytearray(data))
    if n in (158, 191):
        out.append(bytearray(data[126:158]))
    if n >= 32 and n not in (32,):
        out.append(bytearray(data[-32:]))
    if not out:
        raise DecryptError("unrecognised key file")
    return out


def derive_crypt15_key(root_key: bytes | bytearray) -> bytes:
    if len(root_key) != 32:
        raise DecryptError("root key must be 32 bytes")
    private = hmac.new(bytes(32), bytes(root_key), hashlib.sha256).digest()
    return hmac.new(private, b"backup encryption\x01", hashlib.sha256).digest()


# -------------------------------------------------------------------------- header
def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = val = 0
    while True:
        if i >= len(buf) or shift > 63:
            raise DecryptError("malformed header")
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7


def _find_iv(buf: bytes, depth: int = 0) -> bytes | None:
    i, n = 0, len(buf)
    while i < n:
        tag, i = _varint(buf, i)
        wt = tag & 7
        if wt == 0:
            _, i = _varint(buf, i)
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        elif wt == 2:
            ln, i = _varint(buf, i)
            if i + ln > n:
                raise DecryptError("malformed header")
            chunk = buf[i : i + ln]
            i += ln
            if ln == 16:
                return chunk
            if depth < 4 and ln > 0:
                with contextlib.suppress(DecryptError):
                    found = _find_iv(chunk, depth + 1)
                    if found:
                        return found
        else:
            raise DecryptError("malformed header")
    return None


def parse_header(head: bytes) -> tuple[bytes, int]:
    """Return (iv, payload_offset)."""
    if len(head) < 4:
        raise DecryptError("file too short")
    size = head[0]
    off = 1
    if head[1] == 0x01:
        off = 2
    if size == 0 or size > MAX_HEADER or off + size > len(head):
        raise DecryptError("unsupported header")
    iv = _find_iv(head[off : off + size])
    if iv is None:
        raise DecryptError("unsupported header")
    return iv, off + size


# ------------------------------------------------------------------------ decrypt
def _stream_decrypt(
    src: Path,
    dest: Path,
    aes_key: bytes,
    iv: bytes,
    tag: bytes,
    start: int,
    end: int,
    max_out: int,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    dec = Cipher(algorithms.AES(aes_key), modes.GCM(iv, tag)).decryptor()
    zd = zlib.decompressobj()
    written = 0
    with src.open("rb") as fin, open_private(dest) as out:
        fin.seek(start)
        remaining = end - start
        first = True
        while remaining > 0:
            chunk = fin.read(min(_CHUNK, remaining))
            if not chunk:
                raise DecryptError("truncated file")
            remaining -= len(chunk)
            if on_progress:
                on_progress(end - start - remaining, end - start)
            data = dec.update(chunk)
            if first:
                first = False
                # cheap early reject of wrong keys/layouts: zlib stream header check
                if len(data) < 2 or ((data[0] << 8) | data[1]) % 31 != 0 or data[0] & 0x0F != 8:
                    raise DecryptError("bad key or layout")
            buf = data
            while buf:
                plain = zd.decompress(buf, _CHUNK)
                if plain:
                    written += len(plain)
                    if written > max_out:
                        raise DecryptError("output exceeds size limit")
                    out.write(plain)
                buf = zd.unconsumed_tail
        dec.finalize()  # raises InvalidTag when authentication fails
        if not zd.eof:
            raise DecryptError("truncated payload")
    with dest.open("rb") as fh:
        if fh.read(len(SQLITE_MAGIC)) != SQLITE_MAGIC:
            raise DecryptError("decrypted data is not a SQLite database")


def decrypt_backup(
    src: Path,
    dest: Path,
    root_keys: list[bytearray],
    *,
    kind: int | None = None,
    max_output: int = DEFAULT_MAX_OUTPUT,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Decrypt *src* to *dest* (0600). Tries each candidate key; the caller owns/zeroizes keys."""
    if kind is None:
        m = re.search(r"\.crypt(14|15)$", src.name)
        if not m:
            raise DecryptError("unsupported file type")
        kind = int(m.group(1))
    if kind not in (14, 15):
        raise DecryptError("unsupported file type")
    size = src.stat().st_size
    with src.open("rb") as fh:
        head = fh.read(MAX_HEADER + 2)
    iv, payload = parse_header(head)
    for root in root_keys:
        aes_key = derive_crypt15_key(root) if kind == 15 else bytes(root)
        for trailer in (16, 32):  # tag only, or tag + md5
            end = size - trailer
            if end <= payload:
                continue
            with src.open("rb") as fh:
                fh.seek(end)
                tag = fh.read(16)
            try:
                _stream_decrypt(src, dest, aes_key, iv, tag, payload, end, max_output, on_progress)
                return
            except (InvalidTag, zlib.error, DecryptError):
                dest.unlink(missing_ok=True)
    raise DecryptError("decryption failed: wrong key, corrupt file or unsupported format")
