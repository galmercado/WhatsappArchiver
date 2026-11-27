from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from conftest import FAST_KDF, PASSPHRASE
from fakes import SERIAL, FakeADBRunner, ScriptedUI
from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest import contacts as C
from waarchive.ingest.archive import SQLCipherProvider
from waarchive.ingest.device import ADBClient
from waarchive.ingest.normalize import Normalizer, open_source_ro
from waarchive.ingest.pipeline import IngestConfig, Pipeline
from waarchive.keys import KdfParams, derive_master, subkey
from waarchive.media_vault import MediaVault

PNG = gen.tiny_png()
JPG = b"\xff\xd8\xff\xe0" + b"jpegdata" * 4


def entry(
    name: str, *nums: str, photo: bytes | None = None, cid: int | None = None
) -> C.PhonebookEntry:
    return C.PhonebookEntry(
        name=name, numbers=tuple(C.digits(n) for n in nums), photo=photo, source_id=cid
    )


# ------------------------------------------------------------------------------ helpers
def test_sniff_image_accepts_only_safe_raster_formats() -> None:
    assert C.sniff_image(PNG) == "image/png" and C.sniff_image(JPG) == "image/jpeg"
    assert (
        C.sniff_image(b"GIF89a....") == "image/gif"
        and C.sniff_image(b"RIFF\0\0\0\0WEBPVP8 ") == "image/webp"
    )
    for bad in (
        b"",
        b"<svg onload=alert(1)>",
        b"<html>",
        b"%PDF-1.4",
        b"MZ\x90\x00",
        b"\x00" * 20,
        b"#!/bin/sh",
    ):
        assert C.sniff_image(bad) is None


def test_avatar_path_is_opaque_and_stable() -> None:
    a = C.avatar_rel("972501234567@s.whatsapp.net")
    assert (
        a == C.avatar_rel("972501234567@s.whatsapp.net")
        and "972" not in a
        and a.startswith("avatars/")
    )
    assert a != C.avatar_rel("972501234568@s.whatsapp.net")


# ------------------------------------------------------------------------------ matching
@pytest.mark.parametrize(
    "jid,book",
    [
        ("972501234567@s.whatsapp.net", "+972 50-123-4567"),  # international
        ("972501234567@s.whatsapp.net", "050-123-4567"),  # national with trunk 0
        ("15551234567@s.whatsapp.net", "(555) 123-4567"),  # US without country code
        ("15551234567@s.whatsapp.net", "+1 555 123 4567"),
        ("447911123456@s.whatsapp.net", "07911 123456"),  # UK
        ("491701234567@s.whatsapp.net", "0170 1234567"),  # DE
    ],
)
def test_matches_international_and_national_formats(jid: str, book: str) -> None:
    idx = C.PhonebookIndex([entry("Dana", book), entry("Other", "+1 202 555 0000")])
    assert idx.lookup(jid) is not None and idx.lookup(jid).name == "Dana"  # type: ignore[union-attr]


def test_no_match_for_other_people_groups_lids_and_junk() -> None:
    idx = C.PhonebookIndex([entry("Dana", "+972 50 123 4567")])
    for jid in (
        "972501234568@s.whatsapp.net",
        "120363000000000001@g.us",
        "1234567890123@lid",
        "status@broadcast",
        "",
        "x@y",
        "12345@s.whatsapp.net",
    ):
        assert idx.lookup(jid) is None, jid


def test_ambiguous_tails_are_not_guessed() -> None:
    idx = C.PhonebookIndex([entry("Dana", "050 123 4567"), entry("Eli", "+1 050 123 4567")])
    assert idx.lookup("972501234567@s.whatsapp.net") is None or idx.lookup(
        "972501234567@s.whatsapp.net"
    ).name in ("Dana",)  # type: ignore[union-attr]
    clash = C.PhonebookIndex([entry("Dana", "0501234567"), entry("Eli", "0501234567")])
    assert (
        clash.lookup("972501234567@s.whatsapp.net") is None
    )  # two different names for one number: refuse


def test_same_person_saved_twice_still_matches_and_picture_entries_merge_with_names() -> None:
    idx = C.PhonebookIndex(
        [
            entry("Dana", "050 123 4567"),
            entry("Dana", "+972501234567"),
            entry("", "972501234567", photo=PNG),
        ]
    )
    got = idx.lookup("972501234567@s.whatsapp.net")
    assert got is not None and got.name == "Dana" and got.photo == PNG


def test_short_numbers_are_ignored() -> None:
    idx = C.PhonebookIndex([entry("Bank", "1234"), entry("SMS", "55555")])
    assert idx.size == 2 and idx.lookup("1234@s.whatsapp.net") is None


# ----------------------------------------------------------------------------------- vCard
def test_parse_vcf_v3_with_folded_photo() -> None:
    photo = base64.b64encode(PNG).decode()
    folded = "\r\n ".join(photo[i : i + 20] for i in range(0, len(photo), 20))
    text = f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Alice A\r\nTEL;TYPE=CELL:+1 555 0100 101\r\nTEL;TYPE=HOME:555-0100-103\r\nPHOTO;ENCODING=b;TYPE=PNG:{folded}\r\nEND:VCARD\r\n"
    [e] = C.parse_vcf(text)
    assert e.name == "Alice A" and e.numbers == ("15550100101", "5550100103") and e.photo == PNG


def test_parse_vcf_v21_quoted_printable_utf8_and_structured_name_fallback() -> None:
    text = (
        "BEGIN:VCARD\nVERSION:2.1\nFN;CHARSET=UTF-8;ENCODING=QUOTED-PRINTABLE:=D7=93=D7=A0=D7=94 =D7=9B=D7=94=D7=9F\n"
        "TEL;CELL:0501234567\nEND:VCARD\n"
        "BEGIN:VCARD\nVERSION:3.0\nN:Smith;John;;;\nitem1.TEL;type=pref:+44 20 7946 0958\nEND:VCARD\n"
    )
    a, b = C.parse_vcf(text)
    assert a.name == "דנה כהן" and a.numbers == ("0501234567",)
    assert b.name == "John Smith" and b.numbers == ("442079460958",)


def test_parse_vcf_skips_cards_without_numbers_bad_photos_and_garbage() -> None:
    svg = base64.b64encode(b"<svg onload=alert(1)>").decode()
    text = (
        "garbage\nBEGIN:VCARD\nFN:No Number\nEND:VCARD\n"
        f"BEGIN:VCARD\nFN:Evil Photo\nTEL:+1 555 010 0199\nPHOTO;ENCODING=b;TYPE=SVG:{svg}\nEND:VCARD\n"
        "BEGIN:VCARD\nFN:Broken\nTEL:+1 555 010 0198\nPHOTO;ENCODING=b:!!!notbase64!!!\nEND:VCARD\nBEGIN:VCARD\nFN:Unterminated\nTEL:5550100197\n"
    )
    got = {e.name: e for e in C.parse_vcf(text)}
    assert set(got) == {"Evil Photo", "Broken"} and all(e.photo is None for e in got.values())
    assert C.parse_vcf("") == [] and C.parse_vcf("\x00\x01\x02") == []


def test_load_vcf_and_avatar_dir_guard_inputs(tmp_path: Path) -> None:
    with pytest.raises(C.PhonebookError):
        C.load_vcf(tmp_path / "missing.vcf")
    real = tmp_path / "c.vcf"
    real.write_text(gen.sample_vcf())
    assert [e.name for e in C.load_vcf(real)] == [
        "Alice (phonebook)",
        "Bob Phonebook",
        "Someone Else",
    ]
    if os.name == "posix":
        (tmp_path / "link.vcf").symlink_to(real)
        with pytest.raises(C.PhonebookError):
            C.load_vcf(tmp_path / "link.vcf")
    pics = tmp_path / "pics"
    pics.mkdir()
    (pics / "+972 50 123 4567.png").write_bytes(PNG)
    (pics / "15550100102@s.whatsapp.net.jpg").write_bytes(JPG)
    (pics / "notanumber.png").write_bytes(PNG)
    (pics / "972501234569.jpg").write_bytes(
        b"<html>not an image</html>"
    )  # wrong content for an image name
    (pics / "972501234570.txt").write_bytes(PNG)
    got = C.load_avatar_dir(pics)
    assert sorted(e.numbers[0] for e in got) == ["15550100102", "972501234567"] and all(
        e.name == "" for e in got
    )
    with pytest.raises(C.PhonebookError):
        C.load_avatar_dir(tmp_path / "nope")


# ------------------------------------------------------------------------ phone address book
BOOK = (
    "Row: 0 contact_id=11, display_name=Alice Phone, data1=+1 555 0100 101\n"
    "Row: 1 contact_id=11, display_name=Alice Phone, data1=555-0100-109\n"
    "Row: 2 contact_id=12, display_name=Bob, The Builder, data1=(555) 0100-102\n"
    "Row: 3 contact_id=13, display_name=NULL, data1=+1 555 0100 150\n"
    "Row: 4 contact_id=14, display_name=Shorty, data1=1234\n"
    "this line is noise\n"
)


def test_read_phonebook_groups_numbers_and_handles_commas_nulls_and_noise() -> None:
    got = {e.source_id: e for e in C.read_phonebook(FakeADBRunner(phonebook=BOOK), SERIAL)}
    assert set(got) == {11, 12}
    assert got[11].numbers == ("15550100101", "5550100109") and got[12].name == "Bob, The Builder"


def test_read_phonebook_reports_refusal_and_validates_serial() -> None:
    with pytest.raises(C.PhonebookError):
        C.read_phonebook(FakeADBRunner(phonebook=None), SERIAL)
    with pytest.raises(Exception, match="serial"):
        C.read_phonebook(FakeADBRunner(phonebook=BOOK), "x; reboot")
    assert C.read_phonebook(FakeADBRunner(phonebook="No result found.\n"), SERIAL) == []


def test_read_photo_returns_only_real_images_and_never_injects_shell() -> None:
    r = FakeADBRunner(
        phonebook=BOOK, photos={11: PNG, 12: b"<html>nope</html>", 13: b"x" * (C.MAX_PHOTO + 1)}
    )
    assert C.read_photo(r, SERIAL, 11) == PNG
    assert (
        C.read_photo(r, SERIAL, 12) is None
        and C.read_photo(r, SERIAL, 13) is None
        and C.read_photo(r, SERIAL, 99) is None
    )
    with pytest.raises(ValueError):
        C.read_photo(r, SERIAL, "11; reboot")  # type: ignore[arg-type]
    sent = [" ".join(a) for a in r.log if a and "exec-out" in a]
    assert all("; " not in s for s in sent)


# ----------------------------------------------------------------------- enrich an archive
@pytest.fixture
def arch(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Real SQLCipher archive built WITHOUT wa.db, so every contact is 'derived' (a bare phone number)."""
    paths = gen.generate_all(tmp_path / "m")
    params = KdfParams.fresh(**FAST_KDF)
    master = derive_master(PASSPHRASE.encode(), params)
    db = SQLCipherProvider().create(tmp_path / "a.db", subkey(master, "db"))
    vault = MediaVault(tmp_path / "vault", subkey(master, "media"), subkey(master, "media-name"))
    Normalizer(open_source_ro(paths["msgstore_plain"]), db, media_root=None, vault=vault).run()
    return db, vault


def q(db, sql: str, *a):  # type: ignore[no-untyped-def]
    return db.execute(sql, a).fetchall()


def test_names_and_pictures_are_added_to_unnamed_contacts(arch) -> None:  # type: ignore[no-untyped-def]
    db, vault = arch
    idx = C.PhonebookIndex(C.parse_vcf(gen.sample_vcf()))
    st = C.enrich_archive(db, vault, idx)
    assert (st.named, st.photos) == (2, 1) and st.unmatched >= 1
    assert q(
        db, "SELECT display_name, source, avatar_mime FROM contact WHERE jid=?", gen.ALICE
    ) == [("Alice (phonebook)", "phonebook", "image/png")]
    assert q(db, "SELECT display_name, avatar_mime FROM contact WHERE jid=?", gen.BOB) == [
        ("Bob Phonebook", None)
    ]
    assert vault.read_all(C.avatar_rel(gen.ALICE)) == C.parse_vcf(gen.sample_vcf())[0].photo
    assert q(db, "SELECT display_name FROM contact WHERE jid=?", gen.CAROL) == [
        (None,)
    ]  # not in the address book: untouched


def test_enrich_is_idempotent_and_respects_names_that_whatsapp_already_has(
    arch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    db, vault = arch
    db.execute(
        "UPDATE contact SET display_name='Saved In WhatsApp', source='wa.db' WHERE jid=?",
        (gen.ALICE,),
    )
    db.execute("UPDATE contact SET display_name='push-name', source='push' WHERE jid=?", (gen.BOB,))
    idx = C.PhonebookIndex(C.parse_vcf(gen.sample_vcf()))
    first = C.enrich_archive(db, vault, idx)
    assert q(db, "SELECT display_name FROM contact WHERE jid=?", gen.ALICE) == [
        ("Saved In WhatsApp",)
    ]  # wa.db name wins
    assert q(db, "SELECT display_name, source FROM contact WHERE jid=?", gen.BOB) == [
        ("Bob Phonebook", "phonebook")
    ]  # push name replaced
    second = C.enrich_archive(db, vault, idx)
    assert second.named == 0 and second.photos == 0 and first.photos == 1


def test_old_archives_without_the_picture_column_are_upgraded(arch) -> None:  # type: ignore[no-untyped-def]
    db, vault = arch
    db.execute("ALTER TABLE contact DROP COLUMN avatar_mime")
    C.enrich_archive(db, vault, C.PhonebookIndex(C.parse_vcf(gen.sample_vcf())))
    assert {r[1] for r in db.execute("PRAGMA table_info(contact)").fetchall()} >= {"avatar_mime"}


def test_photo_fetcher_is_lazy_and_rejects_non_images(arch) -> None:  # type: ignore[no-untyped-def]
    db, vault = arch
    asked: list[int] = []

    def fetch(e: C.PhonebookEntry) -> bytes | None:
        asked.append(e.source_id or 0)
        return PNG if e.source_id == 1 else b"<svg onload=1>"

    idx = C.PhonebookIndex(
        [
            entry("Alice", "+1 555 0100 101", cid=1),
            entry("Bob", "+1 555 0100 102", cid=2),
            entry("Nobody", "+9 999 999 9999", cid=3),
        ]
    )
    st = C.enrich_archive(db, vault, idx, fetch_photo=fetch)
    assert (
        sorted(asked) == [1, 2] and st.photos == 1
    )  # never fetched the unmatched contact; SVG rejected
    assert q(db, "SELECT avatar_mime FROM contact WHERE jid=?", gen.BOB) == [(None,)]


def test_group_contacts_are_never_renamed(arch) -> None:  # type: ignore[no-untyped-def]
    db, vault = arch
    C.enrich_archive(db, vault, C.PhonebookIndex([entry("Fake Group Name", "120363000000000001")]))
    assert q(db, "SELECT display_name FROM contact WHERE jid=?", gen.GROUP) == [("Test Group",)]


# --------------------------------------------------------------------- full ingest pipeline
def _run(tmp_path: Path, device_fs: dict[str, bytes], runner_kwargs: dict, **cfg):  # type: ignore[no-untyped-def,type-arg]
    ui = ScriptedUI(answers=["1"], secrets=[gen.ROOT_KEY_HEX])
    fs = {
        k: v for k, v in device_fs.items() if "wa.db" not in k
    }  # unrooted: no contacts database at all
    runner = FakeADBRunner(fs=fs, **runner_kwargs)
    conf = IngestConfig(out_dir=tmp_path / "out", kdf_overrides=FAST_KDF, **cfg)
    res = Pipeline(ADBClient(runner), ui, SQLCipherProvider(), conf).run(
        bytearray(PASSPHRASE.encode())
    )
    return res, ui, runner


def test_unrooted_ingest_gets_names_and_pictures_from_the_phone(
    tmp_path: Path, device_fs: dict[str, bytes]
) -> None:
    book = "Row: 0 contact_id=21, display_name=Alice Phone, data1=+1 555 0100 101\nRow: 1 contact_id=22, display_name=Bob Phone, data1=(555) 0100-102\n"
    res, ui, _ = _run(tmp_path, device_fs, {"phonebook": book, "photos": {21: PNG}})
    assert (res.stats.names_added, res.stats.pictures_added) == (2, 1)
    assert any("Reading contact names" in s for s in ui.said) and any(
        "added 2 names and 1 pictures" in s for s in ui.said
    )
    assert any(b[0] == "Matching contacts" for b in ui.bars)


def test_phone_refusing_the_address_book_is_not_fatal_and_points_to_vcf(
    tmp_path: Path, device_fs: dict[str, bytes]
) -> None:
    res, ui, _ = _run(tmp_path, device_fs, {"phonebook": None})
    assert res.stats.messages > 0 and res.stats.names_added == 0
    assert any(".vcf" in s for s in ui.said)


def test_vcf_and_pictures_folder_work_without_any_phone_access(
    tmp_path: Path, device_fs: dict[str, bytes]
) -> None:
    vcf = tmp_path / "c.vcf"
    vcf.write_text(gen.sample_vcf())
    pics = tmp_path / "pics"
    pics.mkdir()
    (pics / "15550100102.png").write_bytes(PNG)
    res, _, runner = _run(
        tmp_path, device_fs, {"phonebook": None}, vcf=vcf, avatars=pics, use_phonebook=False
    )
    assert (
        res.stats.names_added == 2 and res.stats.pictures_added == 2
    )  # Alice from vcf photo, Bob from folder
    assert not any(
        "content" in " ".join(a) for a in runner.log
    )  # --no-phonebook never touched the contacts provider


# --------------------------------------------------------------- enrich_contacts.py (existing archive)
def test_enrich_command_updates_an_existing_archive_without_the_phone(
    tmp_path: Path, device_fs: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    from waarchive.ingest import enrich_cli

    res, _, _ = _run(tmp_path, device_fs, {"phonebook": None}, use_phonebook=False)
    vcf = tmp_path / "c.vcf"
    vcf.write_text(gen.sample_vcf())
    monkeypatch.setenv(enrich_cli.PASSPHRASE_ENV, PASSPHRASE)
    ui = ScriptedUI()
    rc = enrich_cli.main(
        ["--archive", str(res.archive.parent), "--no-phonebook", "--vcf", str(vcf)], ui=ui
    )
    assert rc == 0 and any("added 2 names and 1 pictures" in s for s in ui.said)
    # the server-side reader sees them
    master = derive_master(
        PASSPHRASE.encode(),
        __import__("waarchive.keys", fromlist=["read_params"]).read_params(
            res.archive.parent / "archive.kdf.json"
        ),
    )
    db = SQLCipherProvider().open(res.archive, subkey(master, "db"), read_only=True)
    assert db.execute(
        "SELECT display_name, avatar_mime FROM contact WHERE jid=?", (gen.ALICE,)
    ).fetchone() == ("Alice (phonebook)", "image/png")


def test_enrich_command_errors_are_friendly(
    tmp_path: Path, device_fs: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    from waarchive.ingest import enrich_cli

    ui = ScriptedUI()
    assert (
        enrich_cli.main(["--archive", str(tmp_path / "none")], ui=ui) == 2
        and "extract_and_ingest.py" in ui.said[0]
    )
    res, _, _ = _run(tmp_path, device_fs, {"phonebook": None}, use_phonebook=False)
    monkeypatch.setenv(enrich_cli.PASSPHRASE_ENV, "wrong passphrase here!!")
    ui2 = ScriptedUI()
    assert (
        enrich_cli.main(["--archive", str(res.archive.parent), "--no-phonebook"], ui=ui2) == 2
        and "did not unlock" in ui2.said[0]
    )
    monkeypatch.setenv(enrich_cli.PASSPHRASE_ENV, PASSPHRASE)
    ui3 = ScriptedUI()
    assert (
        enrich_cli.main(["--archive", str(res.archive.parent), "--no-phonebook"], ui=ui3) == 3
    )  # no source given


# --------------------------------------------------------------------------------- @lid people
def test_lid_participants_resolve_to_their_phone_number(tmp_path: Path) -> None:
    import sqlite3

    paths = gen.generate_all(tmp_path / "m")
    c = sqlite3.connect(paths["msgstore_plain"])
    c.execute("INSERT INTO jid VALUES(7, '9988776655@lid', '9988776655', 'lid')")
    c.execute(
        "CREATE TABLE jid_map(_id INTEGER PRIMARY KEY, lid_row_id INTEGER, jid_row_id INTEGER)"
    )
    c.execute("INSERT INTO jid_map VALUES(1, 7, 3)")  # LID -> Carol's phone JID
    c.execute(
        "INSERT INTO message VALUES(40, 2, 0, 'KEYL', 7, 0, 1700002000000, 0, 'hi from a lid')"
    )
    c.commit()
    c.close()
    master = derive_master(PASSPHRASE.encode(), KdfParams.fresh(**FAST_KDF))
    db = SQLCipherProvider().create(tmp_path / "a.db", subkey(master, "db"))
    Normalizer(open_source_ro(paths["msgstore_plain"]), db).run()
    assert db.execute("SELECT sender_jid FROM message WHERE id=40").fetchone() == (gen.CAROL,)
    assert db.execute("SELECT count(*) FROM contact WHERE jid LIKE '%@lid'").fetchone() == (0,)
