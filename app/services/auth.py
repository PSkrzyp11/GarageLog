"""Accounts and login sessions.

Functions here only flush; the route decides when the whole operation is committed.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User, UserSession
from app.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    password_needs_rehash,
    spend_password_check_time,
    verify_password,
)

SESSION_LIFETIME = timedelta(days=14)


class EmailAlreadyRegisteredError(Exception):
    pass


class WrongPasswordError(Exception):
    pass


def register_user(db: Session, email: str, password: str) -> User:
    """Create an account. `email` must already be normalized (lowercase)."""
    user = User(email=email, password_hash=hash_password(password))
    try:
        # A SAVEPOINT, so a failed insert does not break the rest of the transaction.
        with db.begin_nested():
            db.add(user)
    except IntegrityError as exc:
        # Relying on the UNIQUE constraint (instead of checking first) is also safe when
        # two registrations with the same e-mail arrive at the same time.
        if "uq_users_email" not in str(exc.orig):
            raise
        raise EmailAlreadyRegisteredError from exc
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalars(select(User).where(User.email == email)).one_or_none()
    if user is None:
        spend_password_check_time(password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


def create_session(db: Session, user: User) -> str:
    """Start a new login session and return its token (for the cookie only — never stored)."""
    now = datetime.now(UTC)
    # Housekeeping: drop this user's expired sessions so the table does not grow forever.
    db.execute(
        delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at <= now)
    )

    token = generate_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=now + SESSION_LIFETIME,
        )
    )
    db.flush()
    return token


def get_user_by_session_token(db: Session, token: str) -> User | None:
    return db.scalars(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == hash_session_token(token),
            UserSession.expires_at > datetime.now(UTC),
        )
    ).one_or_none()


def delete_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == hash_session_token(token)))


def count_other_sessions(db: Session, user: User, current_token: str) -> int:
    """Active logins of this user on other devices or browsers."""
    return db.scalar(
        select(func.count())
        .select_from(UserSession)
        .where(
            UserSession.user_id == user.id,
            UserSession.token_hash != hash_session_token(current_token),
            UserSession.expires_at > datetime.now(UTC),
        )
    )


def delete_other_sessions(db: Session, user: User, current_token: str) -> None:
    """Log the user out everywhere except in the current browser."""
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.token_hash != hash_session_token(current_token),
        )
    )


def change_password(
    db: Session, user: User, current_password: str, new_password: str, current_token: str
) -> None:
    """The current password is required even though the user is logged in, so someone at an
    unlocked computer cannot take the account over. Other sessions end, because whoever knew
    the old password may be logged in somewhere."""
    if not verify_password(user.password_hash, current_password):
        raise WrongPasswordError
    user.password_hash = hash_password(new_password)
    delete_other_sessions(db, user, current_token)
