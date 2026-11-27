from __future__ import annotations

from pathlib import Path

import pytest

from fixtures import generate_mock_whatsapp as gen
from server_support import BASE, Env


@pytest.fixture
def jpeg(tmp_path: Path) -> bytes:
    d = tmp_path / "m"
    gen.build_media_tree(d)
    return (d / "Media/WhatsApp Images/IMG-0001.jpg").read_bytes()


def get(env: Env, mid: int, rng: str | None = None):  # type: ignore[no-untyped-def]
    return env.client.get(f"/api/media/{mid}", headers={"Range": rng} if rng else {})


def test_full_download_decrypts_and_has_safe_headers(ready: Env, jpeg: bytes) -> None:
    r = get(ready, 12)
    assert r.status_code == 200 and r.content == jpeg
    h = r.headers
    assert (
        h["content-type"] == "image/jpeg"
        and h["accept-ranges"] == "bytes"
        and h["content-length"] == str(len(jpeg))
    )
    assert h["content-disposition"] == "inline" and h["x-content-type-options"] == "nosniff"
    assert h["cache-control"] == "no-store" and "sandbox" in h["content-security-policy"]


@pytest.mark.parametrize(
    "rng,start,end",
    [
        ("bytes=0-0", 0, 0),
        ("bytes=0-9", 0, 9),
        ("bytes=10-", 10, None),
        ("bytes=-16", None, None),
        ("bytes=5-99999", 5, None),
        ("bytes=15-16", 15, 16),
    ],
)
def test_range_requests_206(
    ready: Env, jpeg: bytes, rng: str, start: int | None, end: int | None
) -> None:
    n = len(jpeg)
    if rng == "bytes=-16":
        start, end = n - 16, n - 1
    start = 0 if start is None else start
    end = n - 1 if end is None else end
    r = get(ready, 12, rng)
    assert r.status_code == 206 and r.content == jpeg[start : end + 1]
    assert r.headers["content-range"] == f"bytes {start}-{end}/{n}"
    assert r.headers["content-length"] == str(end - start + 1)


def test_unsatisfiable_range_416(ready: Env, jpeg: bytes) -> None:
    for rng in (f"bytes={len(jpeg)}-", "bytes=99999-100000", "bytes=-0"):
        r = get(ready, 12, rng)
        assert r.status_code == 416 and r.headers["content-range"] == f"bytes */{len(jpeg)}"


@pytest.mark.parametrize(
    "rng",
    ["bytes=0-1,5-6", "bytes=abc", "items=0-5", "bytes=9-3", "bytes=-", "garbage", "bytes=0-1 ; x"],
)
def test_malformed_or_multirange_ignored_full_200(ready: Env, jpeg: bytes, rng: str) -> None:
    r = get(ready, 12, rng)
    assert r.status_code == 200 and r.content == jpeg


def test_voice_note_inline_audio_and_document_is_attachment(ready: Env) -> None:
    ptt = get(ready, 13)
    assert (
        ptt.status_code == 200
        and ptt.headers["content-type"] == "audio/ogg"
        and ptt.headers["content-disposition"] == "inline"
    )
    assert ptt.content.startswith(b"OggS")
    doc = get(ready, 14)
    assert doc.headers["content-type"] == "application/octet-stream"
    assert doc.headers["content-disposition"] == 'attachment; filename="report.pdf"'
    assert doc.content.startswith(b"%PDF")


def test_unknown_and_unstored_media_404(ready: Env) -> None:
    for mid in (1, 999, 16, 17):  # text msg, missing, hostile-path rows that were never stored
        assert get(ready, mid).status_code == 404


@pytest.mark.parametrize(
    "path",
    ["/api/media/..%2f..%2fetc%2fpasswd", "/api/media/../../etc/passwd", "/api/media/%2e%2e", "/api/media/12%00", "/api/media/-1", "/api/media/1e3", "/api/media/0", "/api/media/%2012", "/api/media/12%2f..%2f13", "/media/12", "/static/archive.db",
     "/archive.db", "/../archive.db", "/api/media/Media/WhatsApp%20Images/IMG-0001.jpg"],
)  # fmt: skip
def test_path_traversal_attempts_never_serve_files(ready: Env, path: str) -> None:
    r = ready.client.get(path)
    assert r.status_code in (404, 422, 400, 405), (path, r.status_code)
    assert b"root:" not in r.content and b"SQLite" not in r.content


def test_media_requires_auth_and_unlock(env: Env) -> None:
    assert env.client.get("/api/media/12").status_code == 401
    env.login()
    assert env.client.get("/api/media/12").status_code == 423


def test_media_blobs_on_disk_are_ciphertext_with_opaque_names(ready: Env, jpeg: bytes) -> None:
    files = [p for p in (ready.archive / "media").rglob("*") if p.is_file()]
    assert files and all(jpeg[10:60] not in p.read_bytes() for p in files)
    assert not any(("IMG" in p.name or ".jpg" in p.name) for p in files)


def test_post_to_media_not_allowed(ready: Env) -> None:
    r = ready.client.post("/api/media/12", headers={"Origin": BASE})
    assert r.status_code in (405, 403)
