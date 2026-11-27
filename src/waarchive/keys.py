"""Vault key management: Argon2id passphrase KDF + HKDF subkeys.

The passphrase is never stored. Only a salt and cost parameters are persisted.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .secure_fs import open_private

MIN_PASSPHRASE_LEN = 12
KDF_VERSION = 1


class KeyError_(Exception):
    pass


@dataclass(frozen=True)
class KdfParams:
    salt: bytes
    time_cost: int = 3
    memory_kib: int = 64 * 1024
    parallelism: int = 4

    def to_json(self) -> str:
        return json.dumps(
            {
                "v": KDF_VERSION,
                "salt": base64.b64encode(self.salt).decode("ascii"),
                "t": self.time_cost,
                "m": self.memory_kib,
                "p": self.parallelism,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> KdfParams:
        try:
            d = json.loads(raw)
            if d["v"] != KDF_VERSION:
                raise KeyError_("unsupported KDF version")
            salt = base64.b64decode(d["salt"], validate=True)
            t, m, p = int(d["t"]), int(d["m"]), int(d["p"])
        except (ValueError, KeyError, TypeError) as exc:
            raise KeyError_("invalid KDF parameter file") from exc
        if (
            len(salt) < 16
            or not (1 <= t <= 20)
            or not (8 <= m <= 4 * 1024 * 1024)
            or not (1 <= p <= 16)
        ):
            raise KeyError_("KDF parameters out of range")
        return cls(salt, t, m, p)

    @classmethod
    def fresh(cls, **overrides: int) -> KdfParams:
        return cls(salt=secrets.token_bytes(16), **overrides)


def check_passphrase(passphrase: bytes | bytearray) -> None:
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        raise KeyError_(f"passphrase must be at least {MIN_PASSPHRASE_LEN} characters")


def derive_master(passphrase: bytes | bytearray, params: KdfParams) -> bytearray:
    check_passphrase(passphrase)
    raw = hash_secret_raw(
        bytes(passphrase),
        params.salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_kib,
        parallelism=params.parallelism,
        hash_len=32,
        type=Type.ID,
    )
    return bytearray(raw)


def subkey(master: bytes | bytearray, purpose: str) -> bytes:
    """Domain-separated 32-byte subkey ('db', 'media', 'media-name', ...)."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"waarchive/v1/" + purpose.encode("ascii"),
    ).derive(bytes(master))


def write_params(path: Path, params: KdfParams) -> None:
    with open_private(path) as fh:
        fh.write(params.to_json().encode("ascii"))


def read_params(path: Path) -> KdfParams:
    if path.is_symlink() or not path.is_file():
        raise KeyError_("missing KDF parameter file")
    if (path.stat().st_mode & 0o077) and os.name == "posix":
        raise KeyError_("KDF parameter file permissions too open")
    return KdfParams.from_json(path.read_text(encoding="ascii"))
