"""Chats the user explicitly added to the app (persisted in the database)."""
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AddedChat(Base):
    """One row per Telegram peer the user added to their workspace.

    ``peer_id`` + ``access_hash`` are stored so that Telethon InputPeer
    objects can be rebuilt later — StringSession does not cache entities,
    so the access hash must persist for message fetch/send to work.
    """

    __tablename__ = "added_chats"
    __table_args__ = (
        UniqueConstraint("user_id", "peer_id", name="uq_user_peer"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # Telegram identifiers (BigInteger: IDs exceed 32-bit int)
    peer_id: Mapped[int] = mapped_column(BigInteger)
    access_hash: Mapped[int | None] = mapped_column(BigInteger)
    peer_type: Mapped[str] = mapped_column(String(10), default="user")  # user|chat|channel

    username: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    owner = relationship("User", back_populates="added_chats")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AddedChat id={self.id} peer_id={self.peer_id} title={self.title!r}>"
