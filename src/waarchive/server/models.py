"""Pydantic schemas. Inputs are strict and reject unknown fields."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StrictIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoginIn(StrictIn):
    password: str = Field(min_length=1, max_length=256)
    totp: str = Field(pattern=r"^\d{6}$")


class UnlockIn(StrictIn):
    passphrase: str = Field(min_length=1, max_length=1024)


class StatusOut(BaseModel):
    auth_mode: str
    authenticated: bool
    vault_unlocked: bool
    csrf_token: str | None = None


class OkOut(BaseModel):
    ok: bool = True
    csrf_token: str | None = None


class MediaOut(BaseModel):
    mime: str | None
    size_bytes: int | None
    duration_s: int | None
    width: int | None
    height: int | None
    file_name: str | None
    available: bool
    url: str | None


class QuotedOut(BaseModel):
    message_id: int | None
    text: str | None
    sender_name: str | None
    type: str | None


class MessageOut(BaseModel):
    id: int
    chat_id: int
    from_me: bool
    ts: int
    type: str
    status: int | None
    text: str | None
    sender_id: str | None
    sender_name: str | None
    color_idx: int | None
    system_kind: str | None
    system_target_name: str | None
    media: MediaOut | None
    quoted: QuotedOut | None


class MessagesPage(BaseModel):
    items: list[MessageOut]
    cursor_before: str | None
    cursor_after: str | None
    has_more_before: bool
    has_more_after: bool
    target_id: int | None = None


class LastMessageOut(BaseModel):
    text: str | None
    type: str
    from_me: bool
    ts: int


class ChatOut(BaseModel):
    id: int
    jid: str
    title: str
    subtitle: str | None
    is_group: bool
    archived: bool
    last_message_ts: int | None
    last_message: LastMessageOut | None


class ChatsPage(BaseModel):
    items: list[ChatOut]
    next_cursor: str | None


class ParticipantOut(BaseModel):
    jid: str
    name: str
    color_idx: int


class ChatDetail(ChatOut):
    participants: list[ParticipantOut]


class SearchHit(BaseModel):
    message_id: int
    chat_id: int
    chat_title: str
    ts: int
    from_me: bool
    sender_name: str | None
    type: str
    snippet: str


class SearchPage(BaseModel):
    items: list[SearchHit]
    terms: list[str]
    next_cursor: str | None
