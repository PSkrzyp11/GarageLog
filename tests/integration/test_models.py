from datetime import UTC, datetime, timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Base, User, UserSession


def make_user(email: str = "jan@example.com") -> User:
    return User(email=email, password_hash="not-a-real-hash")


def make_session(user: User, token_hash: str = "a" * 64) -> UserSession:
    return UserSession(
        user_id=user.id, token_hash=token_hash, expires_at=datetime.now(UTC) + timedelta(days=14)
    )


def test_migrations_match_models(db_engine: Engine) -> None:
    # Fails when a model was changed without generating a migration.
    with db_engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert differences == []


def test_user_is_saved_and_read_back(db_session: Session) -> None:
    db_session.add(make_user())
    db_session.commit()

    user = db_session.scalars(select(User).where(User.email == "jan@example.com")).one()

    assert user.id is not None
    assert user.created_at.tzinfo is not None


def test_each_test_starts_with_empty_database(db_session: Session) -> None:
    # The previous test committed a user; the rollback in db_session must have removed it.
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_email_must_be_unique(db_session: Session) -> None:
    db_session.add(make_user())
    db_session.commit()
    db_session.add(make_user())

    with pytest.raises(IntegrityError, match="uq_users_email"):
        db_session.commit()


def test_email_must_be_lowercase(db_session: Session) -> None:
    db_session.add(make_user("Jan@Example.com"))

    with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
        db_session.commit()


def test_session_token_hash_must_be_unique(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.flush()
    db_session.add_all([make_session(user), make_session(user)])

    with pytest.raises(IntegrityError, match="uq_sessions_token_hash"):
        db_session.commit()


def test_deleting_user_deletes_their_sessions(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.flush()
    db_session.add(make_session(user))
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    # ON DELETE CASCADE is enforced by PostgreSQL, not by the ORM.
    assert db_session.scalar(select(func.count()).select_from(UserSession)) == 0
