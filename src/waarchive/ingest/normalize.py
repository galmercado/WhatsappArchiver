"""Normalize WhatsApp msgstore.db / wa.db (modern and legacy schemas) into the archive.

Column access is capability-based: columns are looked up by candidate names in
``PRAGMA table_info`` so missing/renamed optional columns degrade gracefully.
Identifiers interpolated into SQL come only from constant candidate lists that were
also found in the source schema; values are always bound parameters.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from ..media_vault import MediaPathError, MediaVault, safe_join, validate_rel_path
from .archive import DBConnection

log = logging.getLogger(__name__)

MAX_TEXT = 65_536
BATCH = 5_000
_NUL = re.compile("[\x00]")

_MODERN_TYPES = {
    0: "text", 1: "image", 2: "audio", 3: "video", 4: "contact", 5: "location",
    7: "system", 9: "document", 13: "video", 14: "contact", 15: "deleted",
    16: "location", 20: "sticker", 90: "call",
}  # fmt: skip
_LEGACY_TYPES = {
    0: "text", 1: "image", 2: "audio", 3: "video", 4: "contact", 5: "location",
    8: "call", 9: "document", 10: "call", 13: "video", 20: "sticker",
}  # fmt: skip
_STATUS = {0: 0, 4: 1, 5: 2, 6: 2, 8: 2, 13: 3, 14: 3}
_SYSTEM_KINDS = {1: "subject_changed", 11: "group_created", 12: "added", 14: "removed"}


class SchemaError(Exception):
    pass


@dataclass
class IngestStats:
    schema: str = ""
    chats: int = 0
    messages: int = 0
    contacts: int = 0
    media_stored: int = 0
    media_missing: int = 0
    names_added: int = 0
    pictures_added: int = 0


def open_source_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{quote(path.as_posix())}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    }


def _cols(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}  # nosec B608


def _select(
    conn: sqlite3.Connection,
    table: str,
    wanted: Mapping[str, Sequence[str]],
    order: str | None = None,
) -> Iterator[dict[str, object]]:
    """Stream rows with aliases; absent optional columns come back as None."""
    have = _cols(conn, table)
    parts = []
    for alias, candidates in wanted.items():
        col = next((c for c in candidates if c in have), None)
        parts.append(f'"{col}" AS {alias}' if col else f"NULL AS {alias}")
    sql = f'SELECT {", ".join(parts)} FROM "{table}"'  # noqa: S608  # nosec B608
    if order and order in have:
        sql += f' ORDER BY "{order}"'
    cur = conn.execute(sql)
    names = [d[0] for d in cur.description]
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            return
        for row in rows:
            yield dict(zip(names, row, strict=True))


def _clean(value: object, limit: int = MAX_TEXT) -> str | None:
    """Stored verbatim (never HTML-escaped here; the UI renders text as text) minus NULs."""
    if value is None:
        return None
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    return _NUL.sub("", text)[:limit]


def _int(value: object, default: int | None = None) -> int | None:
    try:
        return int(value)  # type: ignore[call-overload,no-any-return,unused-ignore]
    except (TypeError, ValueError):
        return default


def format_phone(jid: str) -> str:
    user = jid.split("@", 1)[0]
    return f"+{user}" if user.isdigit() else user


def _is_group(jid: str) -> bool:
    return jid.endswith("@g.us")


def color_idx(jid: str) -> int:
    return hashlib.sha256(jid.encode("utf-8", "replace")).digest()[0] % 8


class Normalizer:
    def __init__(
        self,
        src: sqlite3.Connection,
        dst: DBConnection,
        *,
        wa: sqlite3.Connection | None = None,
        media_root: Path | None = None,
        vault: MediaVault | None = None,
        progress: Callable[[str, int, int | None], None] | None = None,
    ) -> None:
        self.progress = progress
        self._msg_total: int | None = None
        self._media_total: int | None = None
        self._media_seen = 0
        self.src, self.dst, self.wa = src, dst, wa
        self.media_root, self.vault = media_root, vault
        self.stats = IngestStats()
        self._contacts: dict[str, tuple[str | None, str | None, int]] = {}
        self._known_jids: set[str] = set()
        self._basename_index: dict[str, str] | None = None

    # ------------------------------------------------------------------ public
    def run(self) -> IngestStats:
        tables = _tables(self.src)
        self._msg_total = self._count(tables)
        if {"message", "chat", "jid"} <= tables:
            self.stats.schema = "modern"
            self._load_wa_contacts()
            self._modern()
        elif "messages" in tables:
            self.stats.schema = "legacy"
            self._load_wa_contacts()
            self._legacy()
        else:
            raise SchemaError("unrecognised msgstore schema")
        self._finish()
        self._report("Indexing messages", self.stats.messages, self._msg_total, force=True)
        self._report("Encrypting media", self._media_seen, self._media_total, force=True)
        return self.stats

    def _count(self, tables: set[str]) -> int | None:
        table = (
            "message"
            if {"message", "chat", "jid"} <= tables
            else "messages"
            if "messages" in tables
            else None
        )
        if table is None:
            return None
        try:
            self._media_total = (
                int(self.src.execute("SELECT COUNT(*) FROM message_media").fetchone()[0])
                if "message_media" in tables
                else None
            )
            return int(self.src.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])  # noqa: S608  # nosec B608
        except sqlite3.Error:
            return None

    def _report(self, label: str, done: int, total: int | None, *, force: bool = False) -> None:
        if self.progress and (force or done % 500 == 0):
            self.progress(label, done, total)

    # ----------------------------------------------------------------- contacts
    def _load_wa_contacts(self) -> None:
        if self.wa is None or "wa_contacts" not in _tables(self.wa):
            return
        for r in _select(
            self.wa,
            "wa_contacts",
            {"jid": ["jid"], "dn": ["display_name"], "wn": ["wa_name"], "num": ["number"]},
        ):
            jid = _clean(r["jid"], 256)
            if not jid or "@" not in jid:
                continue
            name = _clean(r["dn"], 256) or _clean(r["wn"], 256)
            self._contacts[jid] = (
                name or None,
                _clean(r["num"], 64),
                1 if _clean(r["dn"], 256) else 2,
            )

    def _ensure_contact(self, jid: str, subject: str | None = None) -> None:
        if jid in self._known_jids:
            return
        self._known_jids.add(jid)
        name, number, from_wa = self._contacts.get(jid, (None, None, 0))
        if _is_group(jid):
            name = subject or name
        phone = None if _is_group(jid) else (number or format_phone(jid))
        self.dst.execute(
            "INSERT OR IGNORE INTO contact(jid, display_name, phone, is_group, source) VALUES(?,?,?,?,?)",
            (
                jid,
                name,
                phone,
                int(_is_group(jid)),
                {1: "wa.db", 2: "push"}.get(from_wa, "derived"),
            ),
        )

    # ------------------------------------------------------------------- media
    def _basenames(self) -> dict[str, str]:
        if self._basename_index is None:
            idx: dict[str, str] = {}
            dup: set[str] = set()
            if self.media_root and self.media_root.is_dir():
                base = self.media_root.resolve()
                for p in base.rglob("*"):
                    if p.is_file() and not p.is_symlink():
                        n = p.name
                        if n in idx:
                            dup.add(n)
                        idx[n] = p.relative_to(base).as_posix()
            for n in dup:
                idx.pop(n, None)
            self._basename_index = idx
        return self._basename_index

    def _store_media(
        self, message_id: int, rel: str | None, fallback_name: str | None
    ) -> str | None:
        """Copy a confined media file into the encrypted vault. Returns the stored rel path."""
        if not (self.media_root and self.vault):
            return None
        candidates: list[str] = []
        for c in (rel, self._basenames().get(fallback_name or "") if fallback_name else None):
            if c:
                candidates.append(c)
        for cand in candidates:
            try:
                clean = validate_rel_path(cand)
                path = safe_join(self.media_root, clean)
            except MediaPathError:
                log.warning("skipped media with unsafe path (message %s)", message_id)
                continue
            if path.is_file():
                self.vault.store(clean, path)
                self.stats.media_stored += 1
                return clean
        self.stats.media_missing += 1
        return None

    # ------------------------------------------------------------------ inserts
    def _insert_message(self, row: tuple[object, ...]) -> None:
        self.dst.execute(
            "INSERT OR REPLACE INTO message(id, chat_id, sender_jid, from_me, ts, type, status, text,"
            " system_kind, system_target_jid, quoted_id, orig_key_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )
        self.stats.messages += 1
        self._report("Indexing messages", self.stats.messages, self._msg_total)

    def _insert_media(
        self, mid: int, rel: str | None, fallback: str | None, mime: object, size: object,
        dur: object, w: object, h: object,
    ) -> None:  # fmt: skip
        stored = self._store_media(mid, rel, fallback)
        self._media_seen += 1
        if self.progress and self._media_seen % 20 == 0:
            self.progress("Encrypting media", self._media_seen, self._media_total)
        self.dst.execute(
            "INSERT OR REPLACE INTO message_media(message_id, rel_path, mime, size_bytes, duration_s,"
            " width, height, stored) VALUES(?,?,?,?,?,?,?,?)",
            (
                mid,
                stored,
                _clean(mime, 128),
                _int(size),
                _int(dur),
                _int(w),
                _int(h),
                int(bool(stored)),
            ),
        )

    @staticmethod
    def _refine_type(base: str, mime: str | None, rel: str | None) -> str:
        if base == "audio":
            m = (mime or "").lower()
            if "opus" in m or "ogg" in m or (rel or "").lower().endswith(".opus"):
                return "ptt"
        return base

    # ------------------------------------------------------------------- modern
    def _modern(self) -> None:
        src = self.src
        jid_of: dict[int, str] = {}
        for r in _select(
            src, "jid", {"id": ["_id"], "raw": ["raw_string"], "user": ["user"], "srv": ["server"]}
        ):
            rid = _int(r["id"])
            raw = _clean(r["raw"], 256) or (
                f"{_clean(r['user'], 128)}@{_clean(r['srv'], 64)}"
                if r["user"] and r["srv"]
                else None
            )
            if rid is not None and raw:
                jid_of[rid] = raw

        if "jid_map" in _tables(src):
            # Newer WhatsApp stores some people as anonymous `@lid` ids; map them back to their phone JID.
            for r in _select(src, "jid_map", {"lid": ["lid_row_id"], "phone": ["jid_row_id"]}):
                lid_id, phone_id = _int(r["lid"]), _int(r["phone"])
                if lid_id is None or phone_id is None or phone_id not in jid_of:
                    continue
                if jid_of.get(lid_id, "").endswith("@lid"):
                    jid_of[lid_id] = jid_of[phone_id]

        chat_jid: dict[int, str] = {}
        for r in _select(
            src, "chat",
            {"id": ["_id"], "jid": ["jid_row_id"], "subject": ["subject"],
             "archived": ["archived"], "sort": ["sort_timestamp"]},
        ):  # fmt: skip
            cid, jr = _int(r["id"]), _int(r["jid"])
            jid = jid_of.get(jr) if jr is not None else None
            if cid is None or not jid:
                continue
            subject = _clean(r["subject"], 256)
            self._ensure_contact(jid, subject)
            self.dst.execute(
                "INSERT OR REPLACE INTO chat(id, jid, subject, last_message_ts, archived) VALUES(?,?,?,?,?)",
                (cid, jid, subject, _int(r["sort"]), int(bool(_int(r["archived"], 0)))),
            )
            chat_jid[cid] = jid
            self.stats.chats += 1

        sys_action: dict[int, int] = {}
        if "message_system" in _tables(src):
            for r in _select(
                src, "message_system", {"mid": ["message_row_id"], "act": ["action_type"]}
            ):
                m, a = _int(r["mid"]), _int(r["act"])
                if m is not None and a is not None:
                    sys_action[m] = a
        sys_target: dict[int, str] = {}
        if "message_system_chat_participant" in _tables(src):
            for r in _select(
                src,
                "message_system_chat_participant",
                {"mid": ["message_row_id"], "u": ["user_jid_row_id"]},
            ):
                m, u = _int(r["mid"]), _int(r["u"])
                if m is not None and u in jid_of:
                    sys_target.setdefault(m, jid_of[u])

        participants: set[tuple[int, str]] = set()
        msg_type: dict[int, str] = {}
        for r in _select(
            src, "message",
            {"id": ["_id"], "chat": ["chat_row_id"], "from_me": ["from_me"], "key": ["key_id"],
             "sender": ["sender_jid_row_id"], "status": ["status"], "ts": ["timestamp"],
             "mtype": ["message_type"], "text": ["text_data", "data"]},
            order="_id",
        ):  # fmt: skip
            mid, cid = _int(r["id"]), _int(r["chat"])
            if mid is None or cid is None or cid not in chat_jid:
                continue
            from_me = int(bool(_int(r["from_me"], 0)))
            sender_row = _int(r["sender"])
            sender = jid_of.get(sender_row) if sender_row else None
            if from_me:
                sender = None
            elif sender is None and not _is_group(chat_jid[cid]):
                sender = chat_jid[cid]
            if sender:
                self._ensure_contact(sender)
                if _is_group(chat_jid[cid]):
                    participants.add((cid, sender))
            mtype = _MODERN_TYPES.get(_int(r["mtype"], 0) or 0, "other")
            msg_type[mid] = mtype
            kind = _SYSTEM_KINDS.get(sys_action[mid], "other") if mid in sys_action else None
            if kind:
                mtype = "system"
            target = sys_target.get(mid)
            if target:
                self._ensure_contact(target)
            self._insert_message(
                (mid, cid, sender, from_me, _int(r["ts"], 0), mtype,
                 _STATUS.get(_int(r["status"], 0) or 0, 1) if from_me else None,
                 _clean(r["text"]), kind, target, None, _clean(r["key"], 128)),
            )  # fmt: skip
            if self.stats.messages % BATCH == 0:
                self.dst.commit()

        if "message_media" in _tables(src):
            for r in _select(
                src, "message_media",
                {"mid": ["message_row_id"], "path": ["file_path"], "mime": ["mime_type"],
                 "size": ["file_size"], "dur": ["media_duration"], "w": ["width"], "h": ["height"],
                 "name": ["media_name"]},
            ):  # fmt: skip
                mid = _int(r["mid"])
                if mid is None or mid not in msg_type:
                    continue
                rel = _clean(r["path"], 1024)
                self._insert_media(
                    mid, rel, _clean(r["name"], 255), r["mime"], r["size"], r["dur"], r["w"], r["h"]
                )
                refined = self._refine_type(msg_type[mid], _clean(r["mime"], 128), rel)
                if refined != msg_type[mid]:
                    self.dst.execute("UPDATE message SET type=? WHERE id=?", (refined, mid))

        if "message_quoted" in _tables(src):
            for r in _select(
                src, "message_quoted",
                {"mid": ["message_row_id"], "parent": ["parent_message_row_id"], "text": ["text_data", "data"],
                 "sender": ["sender_jid_row_id"], "mtype": ["message_type"]},
            ):  # fmt: skip
                mid = _int(r["mid"])
                if mid is None or mid not in msg_type:
                    continue
                parent = _int(r["parent"])
                qs = jid_of.get(_int(r["sender"]) or -1)
                self.dst.execute(
                    "INSERT OR REPLACE INTO message_quoted VALUES(?,?,?,?)",
                    (
                        mid,
                        _clean(r["text"]),
                        qs,
                        _MODERN_TYPES.get(_int(r["mtype"], 0) or 0, "text"),
                    ),
                )
                if parent is not None and parent in msg_type:
                    self.dst.execute("UPDATE message SET quoted_id=? WHERE id=?", (parent, mid))
        self._write_participants(participants)

    # ------------------------------------------------------------------- legacy
    def _legacy(self) -> None:
        src = self.src
        subjects: dict[str, str | None] = {}
        if "chat_list" in _tables(src):
            for r in _select(src, "chat_list", {"jid": ["key_remote_jid"], "subject": ["subject"]}):
                j = _clean(r["jid"], 256)
                if j:
                    subjects[j] = _clean(r["subject"], 256)
        chat_ids: dict[str, int] = {}
        participants: set[tuple[int, str]] = set()
        ids: set[int] = set()
        for r in _select(
            src, "messages",
            {"id": ["_id"], "jid": ["key_remote_jid"], "from_me": ["key_from_me"], "key": ["key_id"],
             "status": ["status"], "text": ["data"], "ts": ["timestamp"], "wtype": ["media_wa_type"],
             "mime": ["media_mime_type"], "size": ["media_size"], "name": ["media_name"],
             "dur": ["media_duration"], "res": ["remote_resource"], "quoted": ["quoted_row_id"],
             "w": ["media_width"], "h": ["media_height"]},
            order="_id",
        ):  # fmt: skip
            mid = _int(r["id"])
            jid = _clean(r["jid"], 256)
            if mid is None or not jid or "@" not in jid:
                continue
            if jid not in chat_ids:
                cid = len(chat_ids) + 1
                chat_ids[jid] = cid
                self._ensure_contact(jid, subjects.get(jid))
                self.dst.execute(
                    "INSERT INTO chat(id, jid, subject, last_message_ts, archived) VALUES(?,?,?,?,0)",
                    (cid, jid, subjects.get(jid), None),
                )
                self.stats.chats += 1
            cid = chat_ids[jid]
            from_me = int(bool(_int(r["from_me"], 0)))
            sender = (
                None if from_me else (_clean(r["res"], 256) or (None if _is_group(jid) else jid))
            )
            if sender:
                self._ensure_contact(sender)
                if _is_group(jid):
                    participants.add((cid, sender))
            wtype = _int(r["wtype"], 0) or 0
            mtype = _LEGACY_TYPES.get(wtype, "other")
            text = _clean(r["text"])
            kind = None
            if _int(r["status"]) == -1 or (
                wtype == 0 and r["key"] is None and not text and not from_me
            ):
                mtype, kind = "system", "other"
            self._insert_message(
                (mid, cid, sender, from_me, _int(r["ts"], 0), mtype,
                 _STATUS.get(_int(r["status"], 0) or 0, 1) if from_me else None,
                 text, kind, None, None, _clean(r["key"], 128)),
            )  # fmt: skip
            ids.add(mid)
            if mtype in ("image", "audio", "video", "document", "sticker"):
                name = _clean(r["name"], 255)
                self._insert_media(mid, None, name, r["mime"], r["size"], r["dur"], r["w"], r["h"])
                refined = self._refine_type(mtype, _clean(r["mime"], 128), name)
                if refined != mtype:
                    self.dst.execute("UPDATE message SET type=? WHERE id=?", (refined, mid))
            q = _int(r["quoted"])
            if q and q in ids:
                self.dst.execute("UPDATE message SET quoted_id=? WHERE id=?", (q, mid))
            if self.stats.messages % BATCH == 0:
                self.dst.commit()
        self._write_participants(participants)

    # ----------------------------------------------------------------- finalize
    def _write_participants(self, participants: set[tuple[int, str]]) -> None:
        self.dst.executemany(
            "INSERT OR IGNORE INTO participant(chat_id, jid, role, color_idx) VALUES(?,?,'member',?)",
            [(c, j, color_idx(j)) for c, j in sorted(participants)],
        )

    def _finish(self) -> None:
        d = self.dst
        d.execute(
            "UPDATE chat SET last_message_ts = (SELECT MAX(ts) FROM message WHERE chat_id = chat.id)"
            " WHERE last_message_ts IS NULL OR last_message_ts = 0"
            " OR EXISTS (SELECT 1 FROM message WHERE chat_id = chat.id)"
        )
        d.execute("INSERT INTO message_fts(message_fts) VALUES('rebuild')")
        d.execute("INSERT INTO message_fts(message_fts) VALUES('optimize')")
        d.execute("INSERT OR REPLACE INTO meta VALUES('source_schema', ?)", (self.stats.schema,))
        self.stats.contacts = int(d.execute("SELECT COUNT(*) FROM contact").fetchone()[0])
        d.commit()
