"""Shared FastAPI dependencies: database session and the logged-in user.

Every page that shows or changes a user's data depends on `CurrentUser`; hiding a link in
the template is never the access check.
"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import SESSION_COOKIE
from app.services import auth as auth_service

DbSession = Annotated[Session, Depends(get_db)]


class LoginRequired(Exception):
    """Raised for anonymous requests to pages that need a user; handled as a redirect."""


def get_current_user(request: Request, db: DbSession) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return auth_service.get_user_by_session_token(db, token)


def require_user(user: Annotated[User | None, Depends(get_current_user)]) -> User:
    if user is None:
        raise LoginRequired
    return user


OptionalUser = Annotated[User | None, Depends(get_current_user)]
CurrentUser = Annotated[User, Depends(require_user)]
