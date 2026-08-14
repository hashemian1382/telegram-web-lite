"""Pydantic schemas for chat data."""
from pydantic import BaseModel, Field


class ChatOut(BaseModel):
    id: int
    title: str
    unread_count: int = 0
    last_message: str | None = None


class ChatListResponse(BaseModel):
    telegram_linked: bool
    chats: list[ChatOut] = Field(default_factory=list)
