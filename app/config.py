"""Application settings — loaded from environment variables / .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (…/telegram-web-lite)
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # ── Database ─────────────────────────────────────────────────
    # SQLite by default; swap in a PostgreSQL URL (Neon, Supabase, …):
    #   DATABASE_URL=postgresql://user:pass@host/db?sslmode=require
    DATABASE_URL: str = "sqlite:///./sqlite.db"

    # ── Telegram API (https://my.telegram.org/apps) ──────────────
    # Global fallback credentials; each user may also provide their own.
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""

    # ── Runtime artefacts ────────────────────────────────────────
    SESSIONS_DIR: Path = BASE_DIR / "sessions"


@lru_cache
def get_settings() -> Settings:
    """Cached accessor — Settings is parsed only once per process."""
    return Settings()


settings = get_settings()
