from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import generate_mock_whatsapp as gen

FAST_KDF = {"time_cost": 1, "memory_kib": 8, "parallelism": 1}
PASSPHRASE = "correct horse battery staple"


@pytest.fixture
def mock(tmp_path: Path) -> dict[str, Path]:
    return gen.generate_all(tmp_path / "mock")


@pytest.fixture
def device_fs(mock: dict[str, Path]) -> dict[str, bytes]:
    """What a phone exposes on shared storage (no private partition)."""
    root = "/sdcard/Android/media/com.whatsapp/WhatsApp"
    fs = {
        f"{root}/Databases/msgstore.db.crypt15": mock["msgstore_crypt"].read_bytes(),
        f"{root}/Databases/wa.db.crypt15": mock["wa_crypt"].read_bytes(),
    }
    for p in mock["media"].rglob("*"):
        if p.is_file():
            fs[f"{root}/{p.relative_to(mock['media']).as_posix()}"] = p.read_bytes()
    return fs
