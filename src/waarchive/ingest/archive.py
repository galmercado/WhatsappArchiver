"""Normalized archive schema and DatabaseProvider implementations."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = 1

DDL = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE contact(
  jid TEXT PRIMARY KEY, display_name TEXT, phone TEXT,
  is_group INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'derived');
CREATE TABLE chat(
  id INTEGER PRIMARY KEY, jid TEXT NOT NULL REFERENCES contact(jid), subject TEXT,
  last_message_ts INTEGER, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE participant(
  chat_id INTEGER NOT NULL REFERENCES chat(id), jid TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'member', color_idx INTEGER NOT NULL,
  PRIMARY KEY(chat_id, jid));
CREATE TABLE message(
  id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chat(id),
  sender_jid TEXT, from_me INTEGER NOT NULL, ts INTEGER NOT NULL,
  type TEXT NOT NULL, status INTEGER, text TEXT,
  system_kind TEXT, system_target_jid TEXT,
  quoted_id INTEGER, orig_key_id TEXT);
CREATE TABLE message_media(
  message_id INTEGER PRIMARY KEY REFERENCES message(id),
  rel_path TEXT, mime TEXT, size_bytes INTEGER, duration_s INTEGER,
  width INTEGER, height INTEGER, stored INTEGER NOT NULL DEFAULT 0);
CREATE TABLE message_quoted(
  message_id INTEGER PRIMARY KEY REFERENCES message(id),
  quoted_text TEXT, quoted_sender_jid TEXT, quoted_type TEXT);
CREATE INDEX idx_msg_chat_ts ON message(chat_id, ts, id);
CREATE INDEX idx_msg_chat_type ON message(chat_id, type);
CREATE INDEX idx_chat_last ON chat(last_message_ts DESC);
CREATE VIRTUAL TABLE message_fts USING fts5(
  text, content='message', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
"""


class DBConnection(Protocol):
    def execute(self, sql: str, params: Any = ..., /) -> Any: ...
    def executemany(self, sql: str, params: Any, /) -> Any: ...
    def executescript(self, sql: str, /) -> Any: ...
    def commit(self) -> None: ...
    def close(self) -> None: ...


class DatabaseProvider(Protocol):
    def create(self, path: Path, key: bytes) -> DBConnection: ...
    def open(self, path: Path, key: bytes, *, read_only: bool = False) -> DBConnection: ...


class WrongKeyError(Exception):
    pass


def _hexkey(key: bytes) -> str:
    if len(key) != 32:
        raise ValueError("database key must be 32 bytes")
    return key.hex()  # hex only => safe to interpolate into PRAGMA


class SQLCipherProvider:
    """AES-256 encrypted SQLite via SQLCipher; the key is a raw 256-bit key."""

    def _connect(self, path: Path, key: bytes, *, read_only: bool) -> DBConnection:
        import sqlcipher3  # type: ignore[import-untyped,unused-ignore]  # noqa: PLC0415

        uri = f"file:{path.as_posix()}?mode={'ro' if read_only else 'rwc'}"
        conn: DBConnection = sqlcipher3.connect(uri, uri=True)
        conn.execute(f"PRAGMA key = \"x'{_hexkey(key)}'\"")  # nosec B608
        conn.execute("PRAGMA cipher_memory_security = ON")
        try:
            conn.execute("SELECT count(*) FROM sqlite_master").fetchall()
        except Exception as exc:
            conn.close()
            raise WrongKeyError("cannot unlock archive database") from exc
        return conn

    def create(self, path: Path, key: bytes) -> DBConnection:
        if path.exists():
            raise FileExistsError("refusing to overwrite an existing archive")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        conn = self._connect(path, key, read_only=False)
        conn.executescript(DDL)
        conn.execute("INSERT INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        conn.commit()
        return conn

    def open(self, path: Path, key: bytes, *, read_only: bool = False) -> DBConnection:
        return self._connect(path, key, read_only=read_only)
