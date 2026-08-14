"""ORM models."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def _utcnow() -> datetime:
    # datetime.utcnow() is deprecated since Python 3.12
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))

    telegram_phone: Mapped[str | None] = mapped_column(String(20))
    # Telethon StringSession — portable, no session files needed.
    telegram_session: Mapped[str | None] = mapped_column(Text)

    # Optional per-user API credentials (fallback: global .env values).
    custom_api_id: Mapped[int | None] = mapped_column(Integer)
    custom_api_hash: Mapped[str | None] = mapped_column(String(100))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    added_chats = relationship(
        "AddedChat", back_populates="owner", cascade="all, delete-orphan"
    )

    @property
    def telegram_linked(self) -> bool:
        """Whether a usable Telegram session exists for this account."""
        return bool(self.telegram_session)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<User id={self.id} username={self.username!r}>"
