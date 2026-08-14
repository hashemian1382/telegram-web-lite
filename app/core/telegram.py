"""Telethon client management.

Authorised sessions are stored as Telethon ``StringSession`` values directly
in the database (``User.telegram_session``), so no ``.session`` files are
needed and the app stays stateless across restarts.

Note: StringSession keeps the *auth key* only — entity (access-hash) cache is
in-memory, so peers the user adds are stored in ``added_chats`` together with
their ``access_hash`` and rebuilt as ``InputPeer`` on demand.
"""
import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.tl import types

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


@asynccontextmanager
async def _connected_client(
    session_string: str,
    api_id: int | None,
    api_hash: str | None,
) -> AsyncIterator[TelegramClient]:
    """Connect an authorised client from a stored StringSession.

    Raises:
        TelegramAPIError(401): session missing/corrupted or no longer authorised
                               — caller should clear the stored session.
        TelegramAPIError(503): credentials missing or Telegram unreachable.
    """
    api_id, api_hash = _resolve_credentials(api_id, api_hash)
    try:
        client = TelegramClient(StringSession(session_string or ""), api_id, api_hash)
    except Exception as exc:  # unparsable stored string (base64/struct errors)
        logger.warning("Stored session string is unusable: %s", exc)
        raise TelegramAPIError(
            "Stored Telegram session is no longer usable — link your account again.",
            status_code=401,
        ) from exc

    try:
        try:
            await client.connect()
        except (OSError, asyncio.TimeoutError) as exc:
            raise TelegramAPIError(
                "Could not reach Telegram servers — check the server network.",
                status_code=503,
            ) from exc
        if not await client.is_user_authorized():
            raise TelegramAPIError(
                "Telegram session is no longer valid — link your account again.",
                status_code=401,
            )
        yield client
    finally:
        if client.is_connected():
            await client.disconnect()


def _map_rpc(exc: Exception, action: str) -> TelegramAPIError:
    """Translate common Telethon/TL errors into user-safe API errors."""
    if isinstance(exc, errors.FloodWaitError):
        return TelegramAPIError(
            f"Too many attempts — try again in {exc.seconds} seconds.", status_code=429
        )
    if isinstance(exc, errors.AuthKeyUnregisteredError):
        return TelegramAPIError(
            "Telegram session is no longer valid — link your account again.",
            status_code=401,
        )
    if isinstance(exc, errors.UserIsBlockedError | errors.ChatWriteForbiddenError):
        return TelegramAPIError(
            "You can't message this user (they blocked you or writing is restricted).",
            status_code=403,
        )
    logger.warning("%s failed with RPC error: %s", action, exc)
    return TelegramAPIError(f"Telegram error: {exc.__class__.__name__}")


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
        except errors.RPCError as exc:
            await client.disconnect()
            raise _map_rpc(exc, "send_code") from exc
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
        except errors.RPCError as exc:
            raise _map_rpc(exc, "verify_code") from exc

        session_string = client.session.save()
        await self._discard(phone)
        return session_string

    async def _discard(self, phone: str) -> None:
        async with self._lock:
            client = self._pending.pop(phone, None)
        if client is not None:
            await client.disconnect()

    # ── Peers & messages ─────────────────────────────────────────
    async def resolve_peer(
        self,
        session_string: str,
        identifier: str,
        api_id: int | None = None,
        api_hash: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a @username or numeric ID to a storable peer record.

        Usernames work for any public account. Numeric IDs only resolve for
        people the account has interacted with (Telegram limitation).
        """
        ident = identifier.strip().lstrip("@").removeprefix("https://t.me/").removeprefix("t.me/")
        if not ident:
            raise TelegramAPIError("Enter a @username or a numeric ID.", status_code=422)
        key: str | int = int(ident) if ident.isdigit() else ident

        async with _connected_client(session_string, api_id, api_hash) as client:
            try:
                entity = await client.get_entity(key)
            except (ValueError, TypeError) as exc:
                raise TelegramAPIError(
                    f"No Telegram account found for '{identifier}'. Public @usernames "
                    "work for anyone; numeric IDs only for people you've interacted with.",
                    status_code=404,
                ) from exc
            except errors.RPCError as exc:
                raise _map_rpc(exc, "resolve_peer") from exc

        if isinstance(entity, types.User):
            title = " ".join(p for p in (entity.first_name, entity.last_name) if p)
            peer_type = "user"
        elif isinstance(entity, (types.Channel,)):
            title = entity.title
            peer_type = "channel"
        else:  # types.Chat (legacy small groups)
            title = entity.title
            peer_type = "chat"

        return {
            "peer_id": int(entity.id),
            "access_hash": getattr(entity, "access_hash", None),
            "peer_type": peer_type,
            "username": getattr(entity, "username", None),
            "title": title or getattr(entity, "username", None) or str(entity.id),
        }

    @staticmethod
    def _input_peer(peer_type: str, peer_id: int, access_hash: int | None):
        """Rebuild the TL input peer from the stored record."""
        if peer_type == "user":
            if access_hash is None:  # should never happen for resolved users
                raise TelegramAPIError("Stored chat is missing its access hash.", status_code=500)
            return types.InputPeerUser(peer_id, access_hash)
        if peer_type == "channel":
            return types.InputPeerChannel(peer_id, access_hash or 0)
        return types.InputPeerChat(peer_id)

    @staticmethod
    def _message_to_dict(msg) -> dict[str, Any]:
        text = msg.message
        if not text:
            text = "📎 Media / unsupported content" if msg.media else ""
        return {
            "id": int(msg.id),
            "text": text,
            "out": bool(msg.out),
            "sender_id": getattr(msg, "sender_id", None),
            "date": msg.date.isoformat() if msg.date else None,
        }

    async def fetch_messages(
        self,
        session_string: str,
        peer_type: str,
        peer_id: int,
        access_hash: int | None,
        api_id: int | None = None,
        api_hash: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch the last ``limit`` messages (oldest → newest) with a peer."""
        peer = self._input_peer(peer_type, peer_id, access_hash)
        async with _connected_client(session_string, api_id, api_hash) as client:
            try:
                messages = await client.get_messages(peer, limit=limit)
            except errors.RPCError as exc:
                raise _map_rpc(exc, "fetch_messages") from exc
        return [self._message_to_dict(m) for m in reversed(messages)]

    async def send_message(
        self,
        session_string: str,
        peer_type: str,
        peer_id: int,
        access_hash: int | None,
        text: str,
        api_id: int | None = None,
        api_hash: str | None = None,
    ) -> dict[str, Any]:
        """Send a text message to a peer; returns the sent message."""
        peer = self._input_peer(peer_type, peer_id, access_hash)
        async with _connected_client(session_string, api_id, api_hash) as client:
            try:
                msg = await client.send_message(peer, text)
            except errors.RPCError as exc:
                raise _map_rpc(exc, "send_message") from exc
        return self._message_to_dict(msg)


# Process-wide singleton used by the routers.
telegram_manager = TelegramManager()
