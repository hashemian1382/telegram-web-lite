"""User-curated chat workspace.

Only the peers the user explicitly adds appear here — never the full
Telegram dialog list. Added chats are persisted in the database.
"""
import logging
import os
import re
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

# Extensions Telethon's `utils.is_image` recognises as a "photo" (it matches
# only png/jpg/jpeg). Anything else is sent as a document unless normalised.
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


# ── Helpers ─────────────────────────────────────────────────────
def _require_linked(user: User) -> None:
    if not user.telegram_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Link your Telegram account first.",
        )


async def _drop_dead_session(user: User, db: DBSession, exc: TelegramAPIError) -> None:
    """Invalid/revoked session → clear it (and the pooled client) so the UI
    offers re-linking."""
    if exc.status_code == 401:
        user.telegram_session = None
        db.commit()
        await telegram_manager.drop_client(user.id)


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


def _safe_filename(name: str | None) -> str:
    """Sanitise a browser-supplied filename (strip path components and any
    control / reserved characters) so it can be used on disk and as the
    Telegram document name."""
    name = os.path.basename(name or "").strip()
    name = re.sub(r"[\x00-\x1f/\\:*?\"<>|]", "_", name).strip(" .")
    return name or "file"


def _is_image(filename: str | None, mime_type: str | None) -> bool:
    return bool(mime_type and mime_type.startswith("image/")) or bool(
        filename and filename.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"))
    )


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
            user_id=user.id,
            session_string=user.telegram_session,
            identifier=payload.identifier,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        await _drop_dead_session(user, db, exc)
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
            user_id=user.id,
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            limit=20,  # only the 20 most recent messages, by design
            after_id=after_id or None,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        await _drop_dead_session(user, db, exc)
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
            user_id=user.id,
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            text=payload.text,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        await _drop_dead_session(user, db, exc)
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
    as_photo: bool | None = Form(default=None),
) -> SentMessageResponse:
    """Upload a photo or file (multipart). The file is spooled to a temp file
    in 1 MB chunks so memory stays flat, then handed to Telethon for the
    (chunked) upload straight to Telegram.

    ``as_photo`` controls how an image is sent:
      * ``None`` (default) → auto: images become photos, everything else its
        natural type (video / audio / document).
      * ``true``  → force as a photo.
      * ``false`` → force as a plain document (a "file").
    """
    _require_linked(user)
    chat = _get_owned_chat(chat_id, user, db)

    safe_name = _safe_filename(file.filename)
    is_image = _is_image(safe_name, file.content_type)

    # force_document only when the caller explicitly wants a file; otherwise
    # let Telethon auto-detect (images → photos, videos → videos, …).
    force_document = (as_photo is False)

    # Choose an on-disk extension so Telethon's detection sees the right type
    # while the *original* name is still preserved via DocumentAttributeFilename.
    if force_document:
        suffix = ".bin"  # guaranteed non-image → a real document
    else:
        ext = os.path.splitext(safe_name)[1].lower()
        if is_image and ext not in _IMAGE_EXTENSIONS:
            # An image whose extension Telethon doesn't recognise as a photo
            # (e.g. .webp/.gif/.bmp, or none) — normalise so it sends as one.
            suffix = ".jpg"
        else:
            suffix = ext

    tmp_dir: str | None = None
    tmp_path: str | None = None
    size = 0
    try:
        tmp_dir = tempfile.mkdtemp(prefix="twl-upload-")
        stem = os.path.splitext(safe_name)[0] or "file"
        tmp_path = os.path.join(tmp_dir, stem + suffix)
        with open(tmp_path, "wb") as tmp:
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
            user_id=user.id,
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            file_path=tmp_path,
            file_name=safe_name,
            mime_type=file.content_type,
            caption=caption,
            force_document=force_document,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        await _drop_dead_session(user, db, exc)
        raise
    finally:
        if tmp_dir and os.path.isdir(tmp_dir):
            for name in os.listdir(tmp_dir):
                try:
                    os.unlink(os.path.join(tmp_dir, name))
                except OSError:
                    pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass
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
                user_id=user.id,
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
            user_id=user.id,
            session_string=user.telegram_session,
            peer_type=chat.peer_type,
            peer_id=chat.peer_id,
            access_hash=chat.access_hash,
            message_id=message_id,
            **_creds(user),
        )
    except TelegramAPIError as exc:
        await _drop_dead_session(user, db, exc)
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
