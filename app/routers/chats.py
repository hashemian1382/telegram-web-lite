"""Chat data endpoints (require a linked Telegram account)."""
from fastapi import APIRouter

from app.core.telegram import telegram_manager
from app.routers.deps import CurrentUser
from app.schemas.chat import ChatListResponse, ChatOut

router = APIRouter()


@router.get("/", response_model=ChatListResponse)
async def get_chats(user: CurrentUser) -> ChatListResponse:
    if not user.telegram_session:
        return ChatListResponse(telegram_linked=False, chats=[])

    dialogs = await telegram_manager.fetch_dialogs(
        session_string=user.telegram_session,
        api_id=user.custom_api_id,
        api_hash=user.custom_api_hash,
    )
    return ChatListResponse(
        telegram_linked=True,
        chats=[ChatOut(**dialog) for dialog in dialogs],
    )
