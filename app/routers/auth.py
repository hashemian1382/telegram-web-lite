"""Account authentication + Telegram account linking."""
import logging

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.core.security import hash_password, verify_password
from app.core.telegram import telegram_manager
from app.models.user import User
from app.routers.deps import CurrentUser, DBSession
from app.schemas.auth import (
    CodeSentResponse,
    SendCodeRequest,
    UserLogin,
    UserOut,
    UserRegister,
    VerifyCodeRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        telegram_linked=user.telegram_linked,
        telegram_phone=user.telegram_phone,
    )


# ── Web account ─────────────────────────────────────────────────
@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: DBSession) -> UserOut:
    exists = db.scalar(select(User.id).where(User.username == payload.username))
    if exists is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username is already taken",
        )
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_out(user)


@router.post("/login", response_model=UserOut)
def login(payload: UserLogin, request: Request, db: DBSession) -> UserOut:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    ok, updated_hash = verify_password(payload.password, user.hashed_password)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    if updated_hash is not None:  # transparent hash upgrade
        user.hashed_password = updated_hash
        db.commit()

    request.session.clear()
    request.session["user_id"] = user.id
    return _to_out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _to_out(user)


# ── Telegram linking ────────────────────────────────────────────
@router.post("/telegram/send-code", response_model=CodeSentResponse)
async def telegram_send_code(
    payload: SendCodeRequest,
    user: CurrentUser,
    db: DBSession,
) -> CodeSentResponse:
    phone_code_hash = await telegram_manager.send_code(
        phone=payload.phone_number,
        api_id=payload.custom_api_id,
        api_hash=payload.custom_api_hash,
    )
    user.telegram_phone = payload.phone_number
    if payload.custom_api_id is not None:
        user.custom_api_id = payload.custom_api_id
        user.custom_api_hash = payload.custom_api_hash
    db.commit()
    return CodeSentResponse(phone_code_hash=phone_code_hash)


@router.post("/telegram/verify-code")
async def telegram_verify_code(
    payload: VerifyCodeRequest,
    user: CurrentUser,
    db: DBSession,
) -> dict:
    session_string = await telegram_manager.verify_code(
        phone=payload.phone_number,
        code=payload.code,
        phone_code_hash=payload.phone_code_hash,
        password=payload.password,
    )
    if session_string is None:
        # Account has 2FA enabled — ask the client to collect the password.
        return {"status": "password_required"}

    user.telegram_session = session_string
    user.telegram_phone = payload.phone_number
    db.commit()
    logger.info("User %s linked Telegram %s", user.username, payload.phone_number)
    return {"status": "linked", "telegram_phone": payload.phone_number}
