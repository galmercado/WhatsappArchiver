"""All SQL for the read API. Every value is a bound parameter; FTS input is sanitized."""

from __future__ import annotations

import base64
import re
from typing import Any

from ..ingest.archive import DBConnection
from .models import (
    ChatDetail,
    ChatOut,
    ChatsPage,
    LastMessageOut,
    MediaOut,
    MessageOut,
    MessagesPage,
    ParticipantOut,
    QuotedOut,
    SearchHit,
    SearchPage,
)


class BadQueryError(ValueError):
    pass


# ----------------------------------------------------------------------------- cursors
_CUR_RE = re.compile(r"^-?\d{1,18}:\d{1,18}$")


def enc_cursor(ts: int, mid: int) -> str:
    return base64.urlsafe_b64encode(f"{ts}:{mid}".encode()).decode().rstrip("=")


def dec_cursor(raw: str) -> tuple[int, int]:
    try:
        if len(raw) > 64:
            raise ValueError
        text = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("ascii")
        if not _CUR_RE.fullmatch(text):
            raise ValueError
        a, b = text.split(":")
        return int(a), int(b)
    except (ValueError, UnicodeDecodeError) as exc:
        raise BadQueryError("invalid cursor") from exc


# -------------------------------------------------------------------------- name helpers
def _local(jid: str | None) -> str | None:
    return jid.split("@", 1)[0] if jid else None


def person_name(display: str | None, phone: str | None, jid: str | None) -> str | None:
    return display or phone or _local(jid)


def chat_title(
    subject: str | None, display: str | None, phone: str | None, jid: str, grp: bool
) -> str:
    if grp:
        return subject or display or "Group"
    return display or phone or _local(jid) or "Unknown"


def like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ------------------------------------------------------------------------------- chats
def has_avatars(conn: DBConnection) -> bool:
    """Archives made before profile pictures existed have no `contact.avatar_mime` column."""
    return any(r[1] == "avatar_mime" for r in conn.execute("PRAGMA table_info(contact)").fetchall())


def _chat_cols(conn: DBConnection) -> str:
    av = "ct.avatar_mime" if has_avatars(conn) else "NULL"
    return (
        "c.id, c.jid, c.subject, c.last_message_ts, c.archived, ct.display_name, ct.phone, ct.is_group, "
        f"{av}, ct.rowid"
    )


def _chat_out(conn: DBConnection, row: tuple[Any, ...]) -> ChatOut:
    cid, jid, subject, last_ts, archived, dn, phone, grp, avatar_mime, contact_rowid = row
    last = conn.execute(
        "SELECT text, type, from_me, ts FROM message WHERE chat_id=? ORDER BY ts DESC, id DESC LIMIT 1",
        (cid,),
    ).fetchone()
    return ChatOut(
        id=cid,
        jid=jid,
        title=chat_title(subject, dn, phone, jid, bool(grp)),
        subtitle=None if grp else (phone or _local(jid)),
        is_group=bool(grp),
        archived=bool(archived),
        avatar_url=f"/api/avatars/{contact_rowid}" if avatar_mime else None,
        last_message_ts=last_ts,
        last_message=LastMessageOut(
            text=(last[0] or "")[:120] if last[0] is not None else None,
            type=last[1],
            from_me=bool(last[2]),
            ts=last[3],
        )
        if last
        else None,
    )


def list_chats(
    conn: DBConnection, *, q: str | None, cursor: str | None, limit: int, archived: bool
) -> ChatsPage:
    where = ["c.archived = ?"]
    args: list[Any] = [int(archived)]
    q = re.sub(r"[\x00-\x1f\x7f]", "", q or "").strip()[:100]  # control chars/NUL never reach SQL
    if q:
        pat = f"%{like_escape(q.lower())}%"
        clause = (
            "lower(coalesce(c.subject, ct.display_name, '')) LIKE ? ESCAPE '\\' "
            "OR lower(coalesce(ct.display_name, '')) LIKE ? ESCAPE '\\' "
            "OR lower(coalesce(ct.phone, '')) LIKE ? ESCAPE '\\'"
        )
        args += [pat, pat, pat]
        digits = re.sub(r"\D", "", q)
        if len(digits) >= 3:
            clause += " OR c.jid LIKE ? ESCAPE '\\'"
            args.append(f"%{digits}%")
        where.append(f"({clause})")
    if cursor:
        ts, cid = dec_cursor(cursor)
        where.append(
            "(coalesce(c.last_message_ts,0) < ? OR (coalesce(c.last_message_ts,0) = ? AND c.id < ?))"
        )
        args += [ts, ts, cid]
    sql = (
        f"SELECT {_chat_cols(conn)} FROM chat c JOIN contact ct ON ct.jid = c.jid "  # noqa: S608  # nosec B608
        f"WHERE {' AND '.join(where)} "
        "ORDER BY coalesce(c.last_message_ts,0) DESC, c.id DESC LIMIT ?"
    )
    rows = conn.execute(sql, [*args, limit + 1]).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    items = [_chat_out(conn, r) for r in rows]
    nxt = enc_cursor(rows[-1][3] or 0, rows[-1][0]) if more and rows else None
    return ChatsPage(items=items, next_cursor=nxt)


def get_chat(conn: DBConnection, chat_id: int) -> ChatDetail | None:
    row = conn.execute(
        f"SELECT {_chat_cols(conn)} FROM chat c JOIN contact ct ON ct.jid = c.jid WHERE c.id = ?",  # noqa: S608  # nosec B608
        (chat_id,),
    ).fetchone()
    if row is None:
        return None
    base = _chat_out(conn, row)
    parts = conn.execute(
        "SELECT p.jid, ct.display_name, ct.phone, p.color_idx FROM participant p "
        "LEFT JOIN contact ct ON ct.jid = p.jid WHERE p.chat_id = ? ORDER BY p.jid",
        (chat_id,),
    ).fetchall()
    return ChatDetail(
        **base.model_dump(),
        participants=[
            ParticipantOut(jid=j, name=person_name(d, p, j) or j, color_idx=c)
            for j, d, p, c in parts
        ],
    )


# ---------------------------------------------------------------------------- messages
_MSG_SQL = (
    "SELECT m.id, m.chat_id, m.sender_jid, m.from_me, m.ts, m.type, m.status, m.text, "
    "m.system_kind, m.system_target_jid, m.quoted_id, "
    "mm.mime, mm.size_bytes, mm.duration_s, mm.width, mm.height, mm.stored, mm.message_id, mm.rel_path, "
    "q.quoted_text, q.quoted_sender_jid, q.quoted_type, "
    "sc.display_name, sc.phone, p.color_idx, tc.display_name, tc.phone, qc.display_name, qc.phone "
    "FROM message m "
    "LEFT JOIN message_media mm ON mm.message_id = m.id "
    "LEFT JOIN message_quoted q ON q.message_id = m.id "
    "LEFT JOIN contact sc ON sc.jid = m.sender_jid "
    "LEFT JOIN participant p ON p.chat_id = m.chat_id AND p.jid = m.sender_jid "
    "LEFT JOIN contact tc ON tc.jid = m.system_target_jid "
    "LEFT JOIN contact qc ON qc.jid = q.quoted_sender_jid "
)


def _safe_name(rel: str | None) -> str | None:
    if not rel:
        return None
    name = re.sub(r"[^\w.\- ()]", "_", rel.rsplit("/", 1)[-1])[:120]
    return name or None


def _msg_out(r: tuple[Any, ...]) -> MessageOut:
    (mid, cid, sender, from_me, ts, mtype, status, text, skind, starget, quoted_id,
     mime, size, dur, w, h, stored, has_media, rel_path, qtext, qsender, qtype,
     sdn, sph, color, tdn, tph, qdn, qph) = r  # fmt: skip
    media = None
    if has_media is not None:
        media = MediaOut(
            mime=mime, size_bytes=size, duration_s=dur, width=w, height=h,
            file_name=_safe_name(rel_path) if stored else None,
            available=bool(stored), url=f"/api/media/{mid}" if stored else None,
        )  # fmt: skip
    quoted = None
    if quoted_id is not None or qtext is not None:
        quoted = QuotedOut(
            message_id=quoted_id, text=(qtext or "")[:300] if qtext is not None else None,
            sender_name=person_name(qdn, qph, qsender), type=qtype,
        )  # fmt: skip
    return MessageOut(
        id=mid, chat_id=cid, from_me=bool(from_me), ts=ts, type=mtype, status=status, text=text,
        sender_id=sender, sender_name=person_name(sdn, sph, sender) if not from_me else None,
        color_idx=color, system_kind=skind, system_target_name=person_name(tdn, tph, starget),
        media=media, quoted=quoted,
    )  # fmt: skip


def _page(
    rows_asc: list[tuple[Any, ...]], more_before: bool, more_after: bool, target: int | None
) -> MessagesPage:
    items = [_msg_out(r) for r in rows_asc]
    return MessagesPage(
        items=items,
        cursor_before=enc_cursor(items[0].ts, items[0].id) if items else None,
        cursor_after=enc_cursor(items[-1].ts, items[-1].id) if items else None,
        has_more_before=more_before,
        has_more_after=more_after,
        target_id=target,
    )


def list_messages(
    conn: DBConnection,
    chat_id: int,
    *,
    before: str | None,
    after: str | None,
    around: int | None,
    limit: int,
) -> MessagesPage:
    if sum(x is not None for x in (before, after, around)) > 1:
        raise BadQueryError("use only one of before/after/around")
    older = (
        _MSG_SQL
        + "WHERE m.chat_id = ? AND (m.ts < ? OR (m.ts = ? AND m.id < ?)) ORDER BY m.ts DESC, m.id DESC LIMIT ?"
    )
    older_incl = (
        _MSG_SQL
        + "WHERE m.chat_id = ? AND (m.ts < ? OR (m.ts = ? AND m.id <= ?)) ORDER BY m.ts DESC, m.id DESC LIMIT ?"
    )
    newer = (
        _MSG_SQL
        + "WHERE m.chat_id = ? AND (m.ts > ? OR (m.ts = ? AND m.id > ?)) ORDER BY m.ts ASC, m.id ASC LIMIT ?"
    )
    latest = _MSG_SQL + "WHERE m.chat_id = ? ORDER BY m.ts DESC, m.id DESC LIMIT ?"

    if around is not None:
        t = conn.execute(
            "SELECT ts FROM message WHERE id = ? AND chat_id = ?", (around, chat_id)
        ).fetchone()
        if t is None:
            raise LookupError("message not found")
        half = max(limit // 2, 1)
        back = conn.execute(older_incl, (chat_id, t[0], t[0], around, half + 1)).fetchall()
        fwd = conn.execute(newer, (chat_id, t[0], t[0], around, half + 1)).fetchall()
        return _page(back[:half][::-1] + fwd[:half], len(back) > half, len(fwd) > half, around)
    if after is not None:
        ts, mid = dec_cursor(after)
        rows = conn.execute(newer, (chat_id, ts, ts, mid, limit + 1)).fetchall()
        return _page(rows[:limit], True, len(rows) > limit, None)
    if before is not None:
        ts, mid = dec_cursor(before)
        rows = conn.execute(older, (chat_id, ts, ts, mid, limit + 1)).fetchall()
        return _page(rows[:limit][::-1], len(rows) > limit, True, None)
    rows = conn.execute(latest, (chat_id, limit + 1)).fetchall()
    return _page(rows[:limit][::-1], len(rows) > limit, False, None)


# ------------------------------------------------------------------------------ search
MAX_TERMS = 8
MIN_PREFIX = 3
_WORD = re.compile(r"\w+", re.UNICODE)


def fts_terms(raw: str) -> list[str]:
    if len(raw) > 200:
        raise BadQueryError("query too long")
    terms = [t.lower() for t in _WORD.findall(raw) if "_" not in t][:MAX_TERMS]
    terms = [t[:64] for t in terms]
    if not terms:
        raise BadQueryError("query has no searchable words")
    return terms


def fts_match(terms: list[str]) -> str:
    """Quoted tokens only (never operators); trailing prefix match needs >= 3 chars."""
    parts = [f'"{t}"' for t in terms]
    if len(terms[-1]) >= MIN_PREFIX:
        parts[-1] += "*"
    return " ".join(parts)


def make_snippet(text: str, terms: list[str], width: int = 200) -> str:
    low = text.lower()
    idx = min((i for i in (low.find(t) for t in terms) if i >= 0), default=0)
    start = max(0, idx - 60)
    snip = text[start : start + width]
    return ("…" if start > 0 else "") + snip + ("…" if start + width < len(text) else "")


def search_sql(where: list[str]) -> str:
    """Constant SQL fragments only; every value is bound by the caller."""
    return (
        "SELECT m.id, m.chat_id, m.ts, m.from_me, m.type, m.text, c.subject, cc.display_name, cc.phone, "  # noqa: S608
        "cc.is_group, c.jid, sc.display_name, sc.phone, m.sender_jid "
        "FROM message_fts CROSS JOIN message m ON m.id = message_fts.rowid "  # CROSS JOIN pins the FTS index as the driver
        "JOIN chat c ON c.id = m.chat_id JOIN contact cc ON cc.jid = c.jid "
        "LEFT JOIN contact sc ON sc.jid = m.sender_jid "
        f"WHERE {' AND '.join(where)} ORDER BY m.ts DESC, m.id DESC LIMIT ?"  # nosec B608
    )


def search(
    conn: DBConnection, q: str, *, chat_id: int | None, cursor: str | None, limit: int
) -> SearchPage:
    terms = fts_terms(q)
    where = ["message_fts MATCH ?"]
    args: list[Any] = [fts_match(terms)]
    if chat_id is not None:
        where.append("m.chat_id = ?")
        args.append(chat_id)
    if cursor:
        ts, mid = dec_cursor(cursor)
        where.append("(m.ts < ? OR (m.ts = ? AND m.id < ?))")
        args += [ts, ts, mid]
    sql = search_sql(where)
    try:
        rows = conn.execute(sql, [*args, limit + 1]).fetchall()
    except Exception as exc:  # FTS syntax/timeout: never leak engine details
        raise BadQueryError("search failed") from exc
    more = len(rows) > limit
    rows = rows[:limit]
    items = [
        SearchHit(
            message_id=r[0], chat_id=r[1], ts=r[2], from_me=bool(r[3]), type=r[4],
            snippet=make_snippet(r[5] or "", terms),
            chat_title=chat_title(r[6], r[7], r[8], r[10], bool(r[9])),
            sender_name=None if r[3] else person_name(r[11], r[12], r[13]),
        )
        for r in rows
    ]  # fmt: skip
    return SearchPage(
        items=items,
        terms=terms,
        next_cursor=enc_cursor(rows[-1][2], rows[-1][0]) if more and rows else None,
    )


# -------------------------------------------------------------------------------- media
def media_record(conn: DBConnection, message_id: int) -> tuple[str, str | None] | None:
    row = conn.execute(
        "SELECT rel_path, mime FROM message_media WHERE message_id = ? AND stored = 1 AND rel_path IS NOT NULL",
        (message_id,),
    ).fetchone()
    return (row[0], row[1]) if row else None


def avatar_record(conn: DBConnection, contact_rowid: int) -> tuple[str, str] | None:
    """(jid, mime) of a stored profile picture; the file path is derived server-side, never from the client."""
    if not has_avatars(conn):
        return None
    row = conn.execute(
        "SELECT jid, avatar_mime FROM contact WHERE rowid = ? AND avatar_mime IS NOT NULL",
        (contact_rowid,),
    ).fetchone()
    return (row[0], row[1]) if row else None
