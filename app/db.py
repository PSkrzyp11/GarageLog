from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_db_engine(database_url: str) -> Engine:
    # create_engine does not connect yet; the first query does.
    # pool_pre_ping replaces connections dropped e.g. by a database restart.
    return create_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one database session per request, closed afterwards.

    The session does not commit on its own: services only flush, and the route commits once
    the whole operation succeeded. Anything not committed is rolled back when it closes.
    """
    with request.app.state.session_factory() as session:
        yield session
