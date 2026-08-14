"""Shared FastAPI dependencies for routers."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User

DBSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DBSession) -> User:
    """Resolve the logged-in user from the signed session cookie."""
    user_id = request.session.get("user_id")
    user = db.get(User, user_id) if user_id is not None else None
    if user is None or not user.is_active:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
