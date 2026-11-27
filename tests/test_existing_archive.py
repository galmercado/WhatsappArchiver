"""Running extract_and_ingest.py when an archive already exists: detect it, ask, never destroy it silently."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FAST_KDF, PASSPHRASE
from fakes import ScriptedUI
from fixtures import generate_mock_whatsapp as gen
from waarchive.ingest import cli, existing
from waarchive.keys import KdfParams

NEW_PASS = "a brand new vault passphrase"


@pytest.fixture(autouse=True)
def _cheap_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cli.PASSPHRASE_ENV, raising=False)
    real = KdfParams.fresh
    monkeypatch.setattr("waarchive.ingest.pipeline.KdfParams.fresh", lambda **_k: real(**FAST_KDF))


@pytest.fixture
def bundle(tmp_path: Path, mock: dict[str, Path]) -> Path:
    b = tmp_path / "bundle"
    b.mkdir()
    (b / "msgstore.db").write_bytes(mock["msgstore_plain"].read_bytes())
    (b / "wa.db").write_bytes(mock["wa_plain"].read_bytes())
    return b


def run(tmp_path: Path, bundle: Path, ui: ScriptedUI, *extra: str) -> int:
    return cli.main(["--bundle", str(bundle), "--out", str(tmp_path / "archive"), *extra], ui=ui)


@pytest.fixture
def made(tmp_path: Path, bundle: Path) -> Path:
    """An archive created the normal way, protected by PASSPHRASE."""
    assert run(tmp_path, bundle, ScriptedUI(secrets=[PASSPHRASE, PASSPHRASE])) == 0
    return tmp_path / "archive"


def siblings(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("archive"))


def test_fresh_run_is_unchanged_and_never_shows_the_menu(tmp_path: Path, bundle: Path) -> None:
    ui = ScriptedUI(secrets=[PASSPHRASE, PASSPHRASE])
    assert (
        run(tmp_path, bundle, ui) == 0
        and (tmp_path / "archive" / "archive.db").is_file()
        and siblings(tmp_path) == ["archive"]
    )


def test_option_1_checks_the_archive_and_shows_its_contents(
    tmp_path: Path, bundle: Path, made: Path
) -> None:
    ui = ScriptedUI(answers=["1"], secrets=[PASSPHRASE])
    assert run(tmp_path, bundle, ui) == 0
    text = "\n".join(ui.said)
    assert "already exists" in text and "opens correctly" in text
    assert f"{len(gen.MODERN_MESSAGES):,} messages" in text and "3 chats" in text


def test_option_1_wrong_passphrase_is_refused_after_three_tries(
    tmp_path: Path, bundle: Path, made: Path
) -> None:
    ui = ScriptedUI(answers=["1"], secrets=["wrong one", "wrong two", "wrong three"])
    assert run(tmp_path, bundle, ui) == 2
    assert len(ui.alerts) == 3 and "opens correctly" not in "\n".join(ui.said)


def test_option_2_adds_contacts_to_the_existing_archive(
    tmp_path: Path, bundle: Path, made: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vcf = tmp_path / "c.vcf"
    vcf.write_text(gen.sample_vcf())
    ui = ScriptedUI(answers=["2"], secrets=[PASSPHRASE])
    assert run(tmp_path, bundle, ui, "--no-phonebook", "--vcf", str(vcf)) == 0
    assert any("added" in s and "pictures" in s for s in ui.said) and siblings(tmp_path) == [
        "archive"
    ]
    check = ScriptedUI(answers=["1"], secrets=[PASSPHRASE])
    run(tmp_path, bundle, check)
    assert "1 with pictures" in "\n".join(check.said)


def test_option_3_rebuild_keeping_the_existing_passphrase_asks_nothing_more(
    tmp_path: Path, bundle: Path, made: Path
) -> None:
    old_db = (made / "archive.db").read_bytes()
    ui = ScriptedUI(
        answers=["3"], secrets=[PASSPHRASE]
    )  # exactly one secret: no second prompt is allowed
    assert run(tmp_path, bundle, ui) == 0
    backups = [n for n in siblings(tmp_path) if ".previous-" in n]
    assert len(backups) == 1 and siblings(tmp_path) == ["archive", backups[0]]  # no .new debris
    assert (
        tmp_path / backups[0] / "archive.db"
    ).read_bytes() == old_db  # old archive preserved byte for byte
    assert existing.verify_passphrase(
        tmp_path / "archive", PASSPHRASE.encode()
    )  # new one opens with the same passphrase
    assert existing.verify_passphrase(tmp_path / backups[0], PASSPHRASE.encode())
    assert any("previous archive was kept" in s for s in ui.said)
    assert any(b[0] == "Indexing messages" for b in ui.bars)  # progress bars run during the rebuild


def test_option_3_rebuild_with_a_new_passphrase(tmp_path: Path, bundle: Path, made: Path) -> None:
    ui = ScriptedUI(answers=["3", "y"], secrets=["", NEW_PASS, NEW_PASS])
    assert run(tmp_path, bundle, ui) == 0
    assert existing.verify_passphrase(tmp_path / "archive", NEW_PASS.encode())
    assert not existing.verify_passphrase(tmp_path / "archive", PASSPHRASE.encode())
    backup = next(tmp_path / n for n in siblings(tmp_path) if ".previous-" in n)
    assert existing.verify_passphrase(
        backup, PASSPHRASE.encode()
    )  # the old archive still opens with the old passphrase


def test_rebuild_declined_changes_nothing(tmp_path: Path, bundle: Path, made: Path) -> None:
    before = (made / "archive.db").read_bytes()
    ui = ScriptedUI(answers=["3", "n"], secrets=[""])
    assert (
        run(tmp_path, bundle, ui) == 0
        and siblings(tmp_path) == ["archive"]
        and (made / "archive.db").read_bytes() == before
    )


def test_failed_rebuild_leaves_the_old_archive_untouched_and_no_debris(
    tmp_path: Path, made: Path
) -> None:
    empty = tmp_path / "empty_bundle"
    empty.mkdir()  # no usable files -> the rebuild fails
    before = (made / "archive.db").read_bytes()
    ui = ScriptedUI(answers=["3"], secrets=[PASSPHRASE])
    assert cli.main(["--bundle", str(empty), "--out", str(made)], ui=ui) == 2
    assert siblings(tmp_path) == ["archive"] and (made / "archive.db").read_bytes() == before
    assert existing.verify_passphrase(made, PASSPHRASE.encode())


def test_a_stale_half_built_folder_from_an_earlier_crash_is_cleared(
    tmp_path: Path, bundle: Path, made: Path
) -> None:
    stale = tmp_path / "archive.new"
    stale.mkdir()
    (stale / "archive.db").write_bytes(b"half written")
    assert run(tmp_path, bundle, ScriptedUI(answers=["3"], secrets=[PASSPHRASE])) == 0
    assert "archive.new" not in siblings(tmp_path)


@pytest.mark.parametrize("choice", ["4", "", "9", "x"])
def test_cancel_and_unknown_choices_change_nothing(
    tmp_path: Path, bundle: Path, made: Path, choice: str
) -> None:
    before = (made / "archive.db").read_bytes()
    ui = ScriptedUI(answers=[choice])
    assert (
        run(tmp_path, bundle, ui) == 0
        and siblings(tmp_path) == ["archive"]
        and (made / "archive.db").read_bytes() == before
    )
    assert any("Nothing changed" in s for s in ui.said)


def test_unattended_run_refuses_to_touch_an_existing_archive_unless_told(
    tmp_path: Path, bundle: Path, made: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.PASSPHRASE_ENV, NEW_PASS)
    before = (made / "archive.db").read_bytes()
    ui = ScriptedUI()
    assert (
        run(tmp_path, bundle, ui) == 2
        and "--replace" in "\n".join(ui.said)
        and (made / "archive.db").read_bytes() == before
    )
    assert run(tmp_path, bundle, ScriptedUI(), "--replace") == 0
    assert existing.verify_passphrase(tmp_path / "archive", NEW_PASS.encode()) and any(
        ".previous-" in n for n in siblings(tmp_path)
    )


def test_summary_and_helpers(tmp_path: Path, made: Path) -> None:
    s = existing.summarize(made, PASSPHRASE.encode())
    assert (
        (s.chats, s.messages) == (3, len(gen.MODERN_MESSAGES))
        and s.media == 0
        and s.size_bytes > 0  # bundle mode has no media folder
    )
    assert s.named >= 2 and s.pictures == 0
    assert existing.exists(made) and not existing.exists(tmp_path / "nope")
    existing.discard(tmp_path)  # refuses anything that is not our own *.new folder
    assert tmp_path.is_dir()
