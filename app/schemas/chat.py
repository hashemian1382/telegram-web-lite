"""Pydantic schemas for the user-curated chat workspace."""
from datetime import datetime

from pydantic import BaseModel, Field


# ── Added chats (curated list, persisted in DB) ────────────────
class AddChatRequest(BaseModel):
    # @username, t.me/username, or a numeric Telegram ID
    identifier: str = Field(min_length=1, max_length=100)


class AddedChatOut(BaseModel):
    id: int
    peer_id: int
    peer_type: str
    username: str | None = None
    title: str
    added_at: datetime

    model_config = {"from_attributes": True}


class ChatListResponse(BaseModel):
    telegram_linked: bool
    chats: list[AddedChatOut] = Field(default_factory=list)


# ── Messages ────────────────────────────────────────────────────
class MessageOut(BaseModel):
    id: int
    text: str | None = None
    out: bool = False              # True → sent by the current user
    sender_id: int | None = None
    date: str | None = None        # ISO-8601
    # Media metadata (both photos and files) — None for plain text messages
    media_type: str | None = None  # "photo" | "document"
    media_name: str | None = None
    media_size: int | None = None  # bytes
    mime_type: str | None = None


class MessageListResponse(BaseModel):
    chat: AddedChatOut
    messages: list[MessageOut] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class SentMessageResponse(BaseModel):
    message: MessageOut
