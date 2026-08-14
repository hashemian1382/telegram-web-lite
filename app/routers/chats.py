"""User-curated chat workspace.

Only the peers the user explicitly adds appear here — never the full
Telegram dialog list. Added chats are persisted in the database.
"""
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.core.telegram import TelegramAPIError, telegram_manager
from app.models.chat import AddedChat
from app.models.user import User
from app.routers.deps import CurrentUser, DBSession
from app.schemas.chat import (
    AddChatRequest,
    AddedChatOut,
    ChatListResponse,
    MessageListResponse,
    MessageOut,
    SendMessageRequest,
    SentMessageResponse,
)

router = APIRouter()


# ── Helpers ─────────────────────────────────────────────────────
def _require_linked(user: User) -> None:
    if not user.telegram_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Link your Telegram account first.",
        )


def _drop_dead_session(user: User, db: DBSession, exc: TelegramAPIError) -> None:
    """Invalid/revoked session → clear it so the UI offers re-linking."""
    if exc.status_code == 401:
        user.telegram_session = None
        db.commit()
def _get_owned_chat(chat_id: int, user: User, db: DBSession) -> AddedChat:
    chat = db.get(AddedChat, chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found.",
        )
    return chat


def _creds(user: User) -> dict:
    return {"api_id": user.custom_api_id, "api_hash": user.custom_api_hash}


# ── Curated chat list ───────────────────────────────────────────
@router.get("/", response_model=ChatListResponse)
async def list_chats(user: CurrentUser, db: DBSession) -> ChatListResponse:
    if not user.telegram_session:
        return ChatListResponse(telegram_linked=False, chats=[])
    chats = db.scalars(
        select(AddedChat)
        .where(AddedChat.user_id == user.id)
        .order_by(AddedChat.added_at.desc())
    ).all()
    return ChatListResponse(
        telegram_linked=True,
        chats=[AddedChatOut.model_validate(c) for c in chats],
    )


@router.post("/", response_model=AddedChatOut, status_code=status.HTTP_201_CREATED)
async def add_chat(payload: AddChatRequest, user: CurrentUser, db: DBSession) -> AddedChatOut:
    _require_linked(user)
    try:
        peer = await telegram_manager.resolve_peer(
            session_string=user.telegram_session,
            identifier=payload.identifier,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        _drop_dead_session(user, db, exc)
        raise

    existing = db.scalar(
        select(AddedChat).where(
            AddedChat.user_id == user.id, AddedChat.peer_id == peer["peer_id"]
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{existing.title}' is already in your chats.",
        )

    chat = AddedChat(user_id=user.id, **peer)
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return AddedChatOut.model_validate(chat)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_chat(chat_id: int, user: CurrentUser, db: DBSession) -> Response:
    chat = _get_owned_chat(chat_id, user, db)
    db.delete(chat)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Messages ────────────────────────────────────────────────────
@router.get("/{chat_id}/messages", response_model=MessageListResponse)
async def get_messages(chat_id: int, user: CurrentUser, db: DBSession) -> MessageListResponse:
    _require_linked(user)
    chat = _get_owned_chat(chat_id, user, db)
    try:
        messages = await telegram_manager.fetch_messages(
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            limit=20,  # only the 20 most recent messages, by design
            **_creds(user),
        )
    except TelegramAPIError as exc:
        _drop_dead_session(user, db, exc)
        raise
    return MessageListResponse(
        chat=AddedChatOut.model_validate(chat),
        messages=[MessageOut(**m) for m in messages],
    )


@router.post("/{chat_id}/messages", response_model=SentMessageResponse)
async def send_message(
    chat_id: int, payload: SendMessageRequest, user: CurrentUser, db: DBSession
) -> SentMessageResponse:
    _require_linked(user)
    chat = _get_owned_chat(chat_id, user, db)
    try:
        message = await telegram_manager.send_message(
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            text=payload.text,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        _drop_dead_session(user, db, exc)
        raise
    return SentMessageResponse(message=MessageOut(**message))
