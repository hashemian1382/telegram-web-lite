"""Telethon client management.

Authorised sessions are stored as Telethon ``StringSession`` values directly
in the database (``User.telegram_session``), so no ``.session`` files are
needed and the app stays stateless across restarts.
"""
import asyncio
import logging
from typing import Any

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from app.config import settings

logger = logging.getLogger(__name__)


class TelegramAPIError(Exception):
    """Telegram-side failure with a message that is safe to show end users."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _resolve_credentials(api_id: int | None, api_hash: str | None) -> tuple[int, str]:
    """User-provided credentials take priority over the global .env fallback."""
    resolved_id = api_id or settings.TELEGRAM_API_ID
    resolved_hash = api_hash or settings.TELEGRAM_API_HASH
    if not resolved_id or not resolved_hash:
        raise TelegramAPIError(
            "Telegram API credentials are not configured. Set TELEGRAM_API_ID / "
            "TELEGRAM_API_HASH in .env or supply your own credentials.",
            status_code=503,
        )
    return resolved_id, resolved_hash


class TelegramManager:
    """Tracks in-flight (not yet authorised) clients between the
    send-code and verify-code steps, keyed by phone number."""

    def __init__(self) -> None:
        self._pending: dict[str, TelegramClient] = {}
        self._lock = asyncio.Lock()

    # ── Login flow ───────────────────────────────────────────────
    async def send_code(
        self,
        phone: str,
        api_id: int | None = None,
        api_hash: str | None = None,
    ) -> str:
        """Ask Telegram to send a login code; returns ``phone_code_hash``."""
        api_id, api_hash = _resolve_credentials(api_id, api_hash)
        client = TelegramClient(StringSession(), api_id, api_hash)
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
        except errors.ApiIdInvalidError as exc:
            await client.disconnect()
            raise TelegramAPIError("Invalid Telegram API credentials (api_id/api_hash).") from exc
        except errors.PhoneNumberInvalidError as exc:
            await client.disconnect()
            raise TelegramAPIError(
                "Invalid phone number — use international format, e.g. +15551234567."
            ) from exc
        except errors.FloodWaitError as exc:
            await client.disconnect()
            raise TelegramAPIError(
                f"Too many attempts — try again in {exc.seconds} seconds.",
                status_code=429,
            ) from exc
        except errors.RPCError as exc:
            await client.disconnect()
            logger.warning("send_code RPC error: %s", exc)
            raise TelegramAPIError(f"Telegram error: {exc.__class__.__name__}") from exc
        except (OSError, asyncio.TimeoutError) as exc:
            await client.disconnect()
            raise TelegramAPIError(
                "Could not reach Telegram servers — check the server network.",
                status_code=503,
            ) from exc

        # Replace any previous pending attempt for this number.
        async with self._lock:
            old = self._pending.pop(phone, None)
            self._pending[phone] = client
        if old is not None:
            await old.disconnect()
        return sent.phone_code_hash

    async def verify_code(
        self,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None = None,
    ) -> str | None:
        """Complete login and return a storable StringSession.

        Returns ``None`` when the account has two-factor auth enabled and no
        password has been supplied yet — the client stays pending so the user
        can submit the password on a follow-up request.
        """
        async with self._lock:
            client = self._pending.get(phone)
        if client is None:
            raise TelegramAPIError(
                "No pending login for this number — request a new code first.",
                status_code=409,
            )

        try:
            if password:
                # Second step for 2FA-enabled accounts (code already accepted).
                await client.sign_in(phone=phone, password=password)
            else:
                await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        except errors.SessionPasswordNeededError:
            logger.info("2FA password required for %s", phone)
            return None
        except errors.PhoneCodeInvalidError as exc:
            raise TelegramAPIError("The confirmation code is incorrect.") from exc
        except errors.PhoneCodeExpiredError as exc:
            await self._discard(phone)
            raise TelegramAPIError("The confirmation code expired — request a new one.") from exc
        except errors.PasswordHashInvalidError as exc:
            raise TelegramAPIError("The two-factor password is incorrect.") from exc
        except errors.FloodWaitError as exc:
            raise TelegramAPIError(
                f"Too many attempts — try again in {exc.seconds} seconds.",
                status_code=429,
            ) from exc
        except errors.RPCError as exc:
            logger.warning("verify_code RPC error: %s", exc)
            raise TelegramAPIError(f"Telegram error: {exc.__class__.__name__}") from exc

        session_string = client.session.save()
        await self._discard(phone)
        return session_string

    async def _discard(self, phone: str) -> None:
        async with self._lock:
            client = self._pending.pop(phone, None)
        if client is not None:
            await client.disconnect()

    # ── Data ─────────────────────────────────────────────────────
    async def fetch_dialogs(
        self,
        session_string: str,
        api_id: int | None = None,
        api_hash: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch the user's chat list using a saved StringSession."""
        api_id, api_hash = _resolve_credentials(api_id, api_hash)
        try:
            # A malformed/corrupted stored string raises here (base64/struct
            # errors) — treat it the same as an expired session so the caller
            # can clear it and ask the user to re-link.
            client = TelegramClient(StringSession(session_string or ""), api_id, api_hash)
        except Exception as exc:
            logger.warning("Stored session string is unusable: %s", exc)
            raise TelegramAPIError(
                "Stored Telegram session is no longer usable — link your account again.",
                status_code=401,
            ) from exc
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise TelegramAPIError(
                    "Telegram session is no longer valid — link your account again.",
                    status_code=401,
                )
            dialogs = await client.get_dialogs(limit=limit)
        except TelegramAPIError:
            raise
        except errors.RPCError as exc:
            logger.warning("fetch_dialogs RPC error: %s", exc)
            raise TelegramAPIError(f"Telegram error: {exc.__class__.__name__}") from exc
        except (OSError, asyncio.TimeoutError) as exc:
            raise TelegramAPIError(
                "Could not reach Telegram servers — check the server network.",
                status_code=503,
            ) from exc
        finally:
            if client.is_connected():
                await client.disconnect()

        return [
            {
                "id": dialog.id,
                "title": dialog.name or "Unknown",
                "unread_count": dialog.unread_count,
                "last_message": getattr(dialog.message, "message", None),
            }
            for dialog in dialogs
        ]


# Process-wide singleton used by the routers.
telegram_manager = TelegramManager()
