"""Pydantic schemas for account auth and Telegram linking."""
from pydantic import BaseModel, Field

USERNAME_PATTERN = r"^[A-Za-z0-9_.-]{3,50}$"
PHONE_PATTERN = r"^\+?[0-9]{7,15}$"


# ── Web account ─────────────────────────────────────────────────
class UserRegister(BaseModel):
    username: str = Field(pattern=USERNAME_PATTERN)
    password: str = Field(min_length=8, max_length=128)


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    telegram_linked: bool
    telegram_phone: str | None = None


# ── Telegram login flow ─────────────────────────────────────────
class SendCodeRequest(BaseModel):
    phone_number: str = Field(pattern=PHONE_PATTERN)
    custom_api_id: int | None = Field(default=None, gt=0)
    custom_api_hash: str | None = Field(default=None, min_length=16, max_length=64)


class VerifyCodeRequest(BaseModel):
    phone_number: str = Field(pattern=PHONE_PATTERN)
    code: str = Field(pattern=r"^[0-9]{5,6}$")
    phone_code_hash: str = Field(min_length=1)
    password: str | None = Field(default=None, max_length=128)  # 2FA, if required


class CodeSentResponse(BaseModel):
    status: str = "code_sent"
    phone_code_hash: str


class TelegramLinkedResponse(BaseModel):
    status: str = "linked"
    telegram_phone: str
