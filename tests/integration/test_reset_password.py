"""Resetting a forgotten password on the server (scripts/reset_password.py)."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import LoginFailure, UserSession
from scripts import reset_password as command
from tests.integration.helpers import EMAIL, PASSWORD, count, is_logged_in, login, register

NEW_PASSWORD = "nowe hasło od admina"

RunCommand = Callable[..., int]


@pytest.fixture
def run(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> RunCommand:
    """Runs the command against the test database (its commit only releases a savepoint)."""

    @contextmanager
    def test_session() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr(command, "_session", test_session)

    def run_command(*args: str, new_password: str | None = None) -> int:
        if new_password is None:
            monkeypatch.delenv("NEW_PASSWORD", raising=False)
        else:
            monkeypatch.setenv("NEW_PASSWORD", new_password)
        return command.main(list(args))

    return run_command


def test_the_owner_logs_in_with_the_new_password_only(
    client: TestClient, db_session: Session, run: RunCommand
) -> None:
    register(client)
    assert login(client, password="złe hasło").status_code == 400  # a failure on record

    assert run("Jan@Example.com", new_password=NEW_PASSWORD) == 0

    assert not is_logged_in(client)  # every session ended
    assert count(db_session, UserSession) == 0
    assert count(db_session, LoginFailure) == 0
    assert login(client, password=PASSWORD).status_code == 400
    assert login(client, password=NEW_PASSWORD).status_code == 303


def test_a_random_password_is_printed_once(
    client: TestClient, run: RunCommand, capsys: pytest.CaptureFixture[str]
) -> None:
    register(client)

    assert run(EMAIL) == 0

    output = capsys.readouterr().out
    assert f"Password changed for {EMAIL}" in output
    printed = output.split("not stored anywhere): ")[1].strip()
    assert login(client, password=printed).status_code == 303


def test_a_chosen_password_is_not_printed(
    client: TestClient, run: RunCommand, capsys: pytest.CaptureFixture[str]
) -> None:
    register(client)

    run(EMAIL, new_password=NEW_PASSWORD)

    assert NEW_PASSWORD not in capsys.readouterr().out


def test_unknown_account(run: RunCommand, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("nikt@example.com") == 1
    assert "No account with the e-mail nikt@example.com." in capsys.readouterr().err


def test_a_too_short_password_is_refused_before_touching_the_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(command, "_session", lambda: pytest.fail("the database was used"))
    monkeypatch.setenv("NEW_PASSWORD", "krótkie")

    assert command.main([EMAIL]) == 2
    assert "co najmniej 8 znaków" in capsys.readouterr().err
