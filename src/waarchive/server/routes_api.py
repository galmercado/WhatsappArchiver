"""Authenticated, read-only data API: chats, messages, search, media streaming."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from fastapi.responses import Response, StreamingResponse

from ..ingest.contacts import avatar_rel
from ..media_vault import VaultClosedError
from . import queries as Q
from .context import Ctx, require_session, require_unlocked
from .models import ChatDetail, ChatsPage, MessagesPage, SearchPage
from .vault import VaultLockedError

ID = Annotated[int, Path(ge=1, le=2**62)]
LIMIT = Annotated[int, Query(ge=1, le=100)]

INLINE_MIME = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "video/mp4", "video/3gpp", "video/webm",
    "audio/ogg", "audio/opus", "audio/mpeg", "audio/mp4", "audio/aac", "audio/amr", "audio/x-m4a",
}  # fmt: skip
AVATAR_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MEDIA_CSP = "default-src 'none'; sandbox; frame-ancestors 'none'"
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def parse_range(header: str | None, size: int) -> tuple[int, int] | Literal["unsatisfiable"] | None:
    """Single byte-range only. Malformed or multi-range headers are ignored (full 200)."""
    if not header:
        return None
    m = _RANGE_RE.fullmatch(header.strip())
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    a, b = m.groups()
    if a == "":
        n = int(b)
        return "unsatisfiable" if n == 0 or size == 0 else (max(size - n, 0), size - 1)
    start = int(a)
    if start >= size:
        return "unsatisfiable"
    end = int(b) if b else size - 1
    if end < start:
        return None
    return start, min(end, size - 1)


def api_router() -> APIRouter:
    r = APIRouter(dependencies=[Depends(require_session), Depends(require_unlocked)])

    @r.get("/api/chats", response_model=ChatsPage)
    def chats(
        ctx: Ctx,
        q: Annotated[str | None, Query(max_length=100)] = None,
        cursor: Annotated[str | None, Query(max_length=64)] = None,
        limit: LIMIT = 50,
        archived: bool = False,
    ) -> ChatsPage:
        try:
            with ctx.vault.db() as db:
                return Q.list_chats(db, q=q, cursor=cursor, limit=limit, archived=archived)
        except Q.BadQueryError as exc:
            raise HTTPException(400, str(exc)) from None

    @r.get("/api/chats/{chat_id:int}", response_model=ChatDetail)
    def chat(chat_id: ID, ctx: Ctx) -> ChatDetail:
        with ctx.vault.db() as db:
            found = Q.get_chat(db, chat_id)
        if found is None:
            raise HTTPException(404, "not found")
        return found

    @r.get("/api/chats/{chat_id:int}/messages", response_model=MessagesPage)
    def messages(
        chat_id: ID,
        ctx: Ctx,
        before: Annotated[str | None, Query(max_length=64)] = None,
        after: Annotated[str | None, Query(max_length=64)] = None,
        around: Annotated[int | None, Query(ge=1, le=2**62)] = None,
        limit: LIMIT = 50,
    ) -> MessagesPage:
        try:
            with ctx.vault.db() as db:
                if db.execute("SELECT 1 FROM chat WHERE id = ?", (chat_id,)).fetchone() is None:
                    raise HTTPException(404, "not found")
                return Q.list_messages(
                    db, chat_id, before=before, after=after, around=around, limit=limit
                )
        except Q.BadQueryError as exc:
            raise HTTPException(400, str(exc)) from None
        except LookupError:
            raise HTTPException(404, "not found") from None

    @r.get("/api/search", response_model=SearchPage)
    def search(
        ctx: Ctx,
        q: Annotated[str, Query(min_length=1, max_length=200)],
        chat_id: Annotated[int | None, Query(ge=1, le=2**62)] = None,
        cursor: Annotated[str | None, Query(max_length=64)] = None,
        limit: LIMIT = 30,
    ) -> SearchPage:
        try:
            with ctx.vault.db() as db:
                return Q.search(db, q, chat_id=chat_id, cursor=cursor, limit=limit)
        except Q.BadQueryError as exc:
            raise HTTPException(400, str(exc)) from None

    @r.get("/api/avatars/{contact_id:int}")
    def avatar(contact_id: ID, ctx: Ctx) -> Response:
        try:
            with ctx.vault.db() as db:
                rec = Q.avatar_record(db, contact_id)
            if rec is None or rec[1] not in AVATAR_MIME:
                raise HTTPException(404, "not found")
            data = ctx.vault.media.read_all(avatar_rel(rec[0]))
        except (FileNotFoundError, VaultClosedError, VaultLockedError, ValueError):
            raise HTTPException(404, "not found") from None
        return Response(
            content=data,
            media_type=rec[1],
            headers={"Content-Security-Policy": MEDIA_CSP, "Content-Disposition": "inline"},
        )

    @r.get("/api/media/{message_id:int}")
    def media(
        message_id: ID,
        ctx: Ctx,
        range_header: Annotated[str | None, Header(alias="Range", max_length=128)] = None,
    ) -> Response:
        try:
            with ctx.vault.db() as db:
                rec = Q.media_record(db, message_id)  # path comes from the DB, never the client
            if rec is None:
                raise HTTPException(404, "not found")
            rel, mime = rec
            vault = ctx.vault.media
            size = vault.size(rel)
        except (FileNotFoundError, VaultClosedError, VaultLockedError, ValueError):
            raise HTTPException(404, "not found") from None

        base_mime = (mime or "").split(";")[0].strip().lower()
        inline = base_mime in INLINE_MIME
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Security-Policy": MEDIA_CSP,
            "Content-Disposition": "inline"
            if inline
            else f'attachment; filename="{_SAFE_NAME.sub("_", rel.rsplit("/", 1)[-1])[:80] or "download"}"',
        }
        ctype = base_mime if inline else "application/octet-stream"
        rng = parse_range(range_header, size)
        if rng == "unsatisfiable":
            return Response(
                status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"}
            )
        start, end = rng if rng else (0, size - 1)
        status = 206 if rng else 200
        if rng:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(0 if size == 0 else end - start + 1)
        body: Iterator[bytes] = iter(()) if size == 0 else vault.read_range(rel, start, end)
        return StreamingResponse(body, status_code=status, media_type=ctype, headers=headers)

    return r
