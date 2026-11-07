"""Set a new password for an account, e.g. when its owner forgot it (the app sends no e-mails).

    docker compose exec app python -m scripts.reset_password jan@example.com
    cd deploy && docker compose exec app python -m scripts.reset_password jan@example.com
    NEW_PASSWORD=... uv run python -m scripts.reset_password jan@example.com

A random password is generated and printed once (give it to the owner, who can change it on
the "Konto" page); NEW_PASSWORD sets a chosen one instead. Every session of the account ends
and its failed logins are forgotten.
"""

import argparse
import os
import secrets
import sys
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas import check_new_password
from app.services import auth as auth_service


@contextmanager
def _session() -> Iterator[Session]:
    engine = create_engine(get_settings().database_url)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email", help="the e-mail address of the account")
    args = parser.parse_args(argv)

    chosen = os.environ.get("NEW_PASSWORD")
    password = chosen or secrets.token_urlsafe(12)
    try:
        check_new_password(password)  # the same rules as the sign-up form
    except ValueError as exc:
        print(f"NEW_PASSWORD: {exc}", file=sys.stderr)
        return 2

    with _session() as db:
        try:
            user = auth_service.reset_password(db, args.email, password)
        except auth_service.UnknownAccountError:
            print(f"No account with the e-mail {args.email}.", file=sys.stderr)
            return 1
        db.commit()
        email = user.email

    print(f"Password changed for {email}; all its sessions have ended.")
    if not chosen:
        print(f"New password (shown once, not stored anywhere): {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
