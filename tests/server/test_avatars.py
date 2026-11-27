from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import FAST_KDF, PASSPHRASE
from fixtures import generate_mock_whatsapp as gen
from server_support import Env
from waarchive.ingest.archive import SQLCipherProvider
from waarchive.ingest.contacts import parse_vcf
from waarchive.ingest.normalize import Normalizer, open_source_ro
from waarchive.keys import KdfParams, derive_master, subkey
from waarchive.server import queries as Q

ALICE_PNG = parse_vcf(gen.sample_vcf())[0].photo


def by_jid(env: Env) -> dict[str, dict]:  # type: ignore[type-arg]
    return {
        c["jid"]: c
        for c in env.client.get("/api/chats", params={"archived": "false"}).json()["items"]
    }


def test_chat_list_and_detail_expose_avatar_url_only_where_a_picture_exists(ready: Env) -> None:
    chats = by_jid(ready)
    assert re.fullmatch(r"/api/avatars/\d+", chats[gen.ALICE]["avatar_url"])
    assert chats[gen.GROUP]["avatar_url"] is None
    detail = ready.client.get(f"/api/chats/{chats[gen.ALICE]['id']}").json()
    assert detail["avatar_url"] == chats[gen.ALICE]["avatar_url"]


def test_avatar_is_served_decrypted_with_locked_down_headers(ready: Env) -> None:
    url = by_jid(ready)[gen.ALICE]["avatar_url"]
    r = ready.client.get(url)
    assert (
        r.status_code == 200 and r.content == ALICE_PNG and r.headers["content-type"] == "image/png"
    )
    assert (
        r.headers["x-content-type-options"] == "nosniff"
        and r.headers["cache-control"] == "no-store"
    )
    assert (
        "sandbox" in r.headers["content-security-policy"]
        and r.headers["content-disposition"] == "inline"
    )
    on_disk = b"".join(p.read_bytes() for p in (ready.archive / "media").rglob("*") if p.is_file())
    assert ALICE_PNG[:30] not in on_disk  # stored encrypted, not as a recognisable PNG


def test_avatar_requires_login_and_unlocked_vault(env: Env) -> None:
    assert env.client.get("/api/avatars/1").status_code == 401
    env.login()
    assert env.client.get("/api/avatars/1").status_code == 423


@pytest.mark.parametrize(
    "path",
    [
        "/api/avatars/999999",
        "/api/avatars/0",
        "/api/avatars/-1",
        "/api/avatars/abc",
        "/api/avatars/1%2f..%2f2",
        "/api/avatars/1;2",
        "/api/avatars/%20",
    ],
)
def test_unknown_or_malformed_avatar_ids_are_refused(ready: Env, path: str) -> None:
    assert ready.client.get(path).status_code in (404, 422)


def test_contacts_without_a_picture_return_404_and_ids_are_not_path_tricks(ready: Env) -> None:
    with ready.ctx.vault.db() as db:
        rowid = db.execute("SELECT rowid FROM contact WHERE jid=?", (gen.BOB,)).fetchone()[0]
    assert ready.client.get(f"/api/avatars/{rowid}").status_code == 404


def test_non_image_mime_in_the_database_is_never_served(ready: Env) -> None:
    """Even if a row were tampered with, only raster image types are allowed through."""
    url = by_jid(ready)[gen.ALICE]["avatar_url"]
    rowid = int(url.rsplit("/", 1)[1])
    with ready.ctx.vault.db() as db:
        assert Q.avatar_record(db, rowid) == (gen.ALICE, "image/png")
    from waarchive.server.routes_api import AVATAR_MIME

    assert "image/svg+xml" not in AVATAR_MIME and "text/html" not in AVATAR_MIME


def test_archives_from_before_pictures_existed_still_work(tmp_path: Path) -> None:
    paths = gen.generate_all(tmp_path / "m")
    master = derive_master(PASSPHRASE.encode(), KdfParams.fresh(**FAST_KDF))
    db = SQLCipherProvider().create(tmp_path / "a.db", subkey(master, "db"))
    Normalizer(open_source_ro(paths["msgstore_plain"]), db).run()
    db.execute("ALTER TABLE contact DROP COLUMN avatar_mime")
    page = Q.list_chats(db, q=None, cursor=None, limit=10, archived=False)
    assert page.items and all(c.avatar_url is None for c in page.items)
    assert Q.get_chat(db, page.items[0].id) is not None and Q.avatar_record(db, 1) is None
