"""Chat data endpoints (require a linked Telegram account)."""
from fastapi import APIRouter

from app.core.telegram import TelegramAPIError, telegram_manager
from app.routers.deps import CurrentUser, DBSession
from app.schemas.chat import ChatListResponse, ChatOut

router = APIRouter()


@router.get("/", response_model=ChatListResponse)
async def get_chats(user: CurrentUser, db: DBSession) -> ChatListResponse:
    # No stored session → the UI shows the "link Telegram" card.
    if not user.telegram_session:
        return ChatListResponse(telegram_linked=False, chats=[])

    try:
        dialogs = await telegram_manager.fetch_dialogs(
            session_string=user.telegram_session,
            api_id=user.custom_api_id,
            api_hash=user.custom_api_hash,
        )
    except TelegramAPIError as exc:
        if exc.status_code == 401:
            # Session revoked/corrupted/expired → drop it so the UI cleanly
            # falls back to the link card. Transient errors (network, flood
            # wait, ...) keep the stored session untouched.
            user.telegram_session = None
            db.commit()
            return ChatListResponse(telegram_linked=False, chats=[])
        raise

    return ChatListResponse(
        telegram_linked=True,
        chats=[ChatOut(**dialog) for dialog in dialogs],
    )
