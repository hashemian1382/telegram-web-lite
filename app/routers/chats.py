"""User-curated chat workspace.

Only the peers the user explicitly adds appear here — never the full
Telegram dialog list. Added chats are persisted in the database.
"""
import logging
import os
import tempfile
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
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

logger = logging.getLogger(__name__)
router = APIRouter()

# Web upload limit — Telegram itself allows 2 GB, but keeping uploads bounded
# protects the server; raise it here when you have the bandwidth for it.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
_UPLOAD_CHUNK = 1024 * 1024          # 1 MB


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
async def get_messages(
    chat_id: int, user: CurrentUser, db: DBSession, after_id: int = 0
) -> MessageListResponse:
    """``after_id=0`` → last 20 messages; ``after_id=N`` → only messages newer
    than N (incremental auto-refresh polls this every couple of seconds)."""
    _require_linked(user)
    chat = _get_owned_chat(chat_id, user, db)
    try:
        messages = await telegram_manager.fetch_messages(
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            limit=20,  # only the 20 most recent messages, by design
            after_id=after_id or None,
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


# ── Photos & files ──────────────────────────────────────────────
@router.post("/{chat_id}/files", response_model=SentMessageResponse)
async def send_file(
    chat_id: int,
    user: CurrentUser,
    db: DBSession,
    file: UploadFile,
    caption: str | None = Form(default=None, max_length=1024),
) -> SentMessageResponse:
    """Upload a photo or file (multipart). The file is spooled to a temp file
    in 1 MB chunks so memory stays flat, then handed to Telethon for the
    (chunked) upload straight to Telegram."""
    _require_linked(user)
    chat = _get_owned_chat(chat_id, user, db)

    tmp_path: str | None = None
    size = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
            while chunk := await file.read(_UPLOAD_CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File is too large — maximum is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                    )
                tmp.write(chunk)
        if size == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="The uploaded file is empty.",
            )

        message = await telegram_manager.send_file(
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            file_path=tmp_path,
            file_name=file.filename or f"file_{chat_id}",
            mime_type=file.content_type,
            caption=caption,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        _drop_dead_session(user, db, exc)
        raise
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        await file.close()

    return SentMessageResponse(message=MessageOut(**message))


def _content_disposition(disposition: str, filename: str) -> str:
    """RFC 5987 content-disposition with unicode filename support."""
    ascii_fallback = filename.encode("ascii", "ignore").decode().replace('"', "") or "file"
    return (
        f"{disposition}; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )


@router.get("/{chat_id}/messages/{message_id}/download")
async def download_media(
    chat_id: int,
    message_id: int,
    user: CurrentUser,
    db: DBSession,
    thumb: bool = False,
):
    """Download (or preview) the media attached to a message.

    ``?thumb=1`` → small photo preview (inline, cacheable, for chat bubbles).
    Default → full file, streamed from Telegram chunk by chunk; images/videos/
    audio/PDF open inline in the browser, everything else downloads.
    """
    _require_linked(user)
    chat = _get_owned_chat(chat_id, user, db)
    try:
        if thumb:
            data, mime, name = await telegram_manager.download_media_thumb(
                session_string=user.telegram_session,
                peer_type=chat.peer_type,
                peer_id=chat.peer_id,
                access_hash=chat.access_hash,
                message_id=message_id,
                **_creds(user),
            )
            return Response(
                content=data,
                media_type=mime,
                headers={
                    "Content-Disposition": _content_disposition("inline", name),
                    "Cache-Control": "private, max-age=3600",
                },
            )

        stream, name, mime, size = await telegram_manager.open_media_stream(
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            message_id=message_id,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        _drop_dead_session(user, db, exc)
        raise

    disposition = (
        "inline"
        if mime.startswith(("image/", "video/", "audio/")) or mime == "application/pdf"
        else "attachment"
    )
    headers = {"Content-Disposition": _content_disposition(disposition, name)}
    if size:
        headers["Content-Length"] = str(size)
    return StreamingResponse(stream, media_type=mime, headers=headers)
