from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from waarchive.logsafe import RedactingFilter, RedactingFormatter, scrub
from waarchive.secure_fs import secure_tempdir, wipe_tree, zeroize


def test_scrub_removes_pii() -> None:
    text = (
        "msg from 15550100101@s.whatsapp.net group 120363000000000001@g.us "
        "call +1 555 0100 101 key " + "ab" * 32 + " file IMG-0001.jpg token=abc123 report.pdf"
    )
    out = scrub(text)
    for leak in ("15550100101", "g.us", "555 0100", "ab" * 32, "IMG-0001", "abc123", "report.pdf"):
        assert leak not in out


def test_filter_scrubs_exception_traceback(caplog_handler: logging.Handler | None = None) -> None:
    logger = logging.getLogger("t.exc")
    logger.propagate = False
    records: list[str] = []

    class H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    h = H()
    h.setFormatter(RedactingFormatter("%(message)s"))
    h.addFilter(RedactingFilter())
    logger.addHandler(h)
    try:
        raise ValueError("bad jid 15550100101@s.whatsapp.net in IMG-0001.jpg")
    except ValueError:
        logger.error("failed %s", "15550100102@s.whatsapp.net", exc_info=True)
    blob = "\n".join(records)
    assert "15550100101" not in blob and "15550100102" not in blob and "IMG-0001" not in blob


def test_secure_tempdir_is_private_and_wiped() -> None:
    with secure_tempdir() as d:
        assert stat.S_IMODE(d.stat().st_mode) == 0o700
        f = d / "x"
        f.write_bytes(b"secret")
        kept = d
    assert not kept.exists()


def test_secure_tempdir_wiped_on_exception() -> None:
    kept: Path | None = None
    try:
        with secure_tempdir() as d:
            kept = d
            (d / "x").write_bytes(b"s")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert kept is not None and not kept.exists()


def test_wipe_does_not_follow_symlinks(tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    d = tmp_path / "d"
    d.mkdir()
    os.symlink(victim, d / "link")
    wipe_tree(d)
    assert victim.read_text() == "keep me" and not d.exists()


def test_zeroize() -> None:
    b = bytearray(b"secretkey")
    zeroize(b)
    assert b == bytearray(len(b"secretkey"))
