"""Subscribing to the reminders in a calendar app with a secret link."""

import logging
import re

from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.security import HideCalendarTokens, hash_session_token
from tests.integration.helpers import add_car, add_reminder, post_form, register

LINK = re.compile(
    r'id="calendar-url" type="text" readonly value="(http://testserver/calendar/[^"]+)"'
)


def create_link(client: TestClient) -> tuple[Response, str]:
    response = post_form(client, "/account/calendar", {}, form_page="/account")
    match = LINK.search(response.text)
    assert match, "the new link is shown"
    return response, match.group(1)


def fetch_anonymously(client: TestClient, url: str) -> Response:
    """Like a calendar server would: no login cookie."""
    cookies = dict(client.cookies)
    client.cookies.clear()
    try:
        return client.get(url)
    finally:
        for name, value in cookies.items():
            client.cookies.set(name, value)


def test_the_link_is_shown_once_and_only_its_hash_is_stored(
    client: TestClient, db_session: Session
) -> None:
    register(client)

    response, url = create_link(client)

    token = url.removeprefix("http://testserver/calendar/").removesuffix(".ics")
    assert 'href="webcal://testserver/calendar/' in response.text
    stored = db_session.scalars(select(User.calendar_token_hash)).one()
    assert stored == hash_session_token(token) and token not in stored
    page = client.get("/account").text
    assert token not in page
    assert "Link do subskrypcji jest aktywny od" in page


def test_a_calendar_app_gets_the_reminders_without_logging_in(client: TestClient) -> None:
    register(client)
    golf = add_car(client, name="Golf", initial_odometer_km="120000")
    astra = add_car(client, name="Astra", initial_odometer_km="80000", has_lpg="")
    add_reminder(client, golf, title="OC Golfa", due_date="2027-01-15")
    add_reminder(client, astra, title="Przegląd Astry", due_date="2027-03-01")
    _, url = create_link(client)

    response = fetch_anonymously(client, url)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert "content-disposition" not in response.headers  # shown, not downloaded
    assert "SUMMARY:Golf: OC Golfa" in response.text
    assert "SUMMARY:Astra: Przegląd Astry" in response.text


def test_a_new_link_replaces_the_old_one(client: TestClient) -> None:
    register(client)
    _, old = create_link(client)

    _, new = create_link(client)

    assert fetch_anonymously(client, old).status_code == 404
    assert fetch_anonymously(client, new).status_code == 200


def test_a_revoked_link_stops_working(client: TestClient, db_session: Session) -> None:
    register(client)
    _, url = create_link(client)

    response = post_form(client, "/account/calendar/revoke", {}, form_page="/account")

    assert response.headers["location"].endswith("/account?done=calendar_off")
    assert fetch_anonymously(client, url).status_code == 404
    assert db_session.scalars(select(User.calendar_token_hash)).one() is None


def test_unknown_or_malformed_tokens_are_not_found(client: TestClient) -> None:
    assert client.get("/calendar/zgadywanie.ics").status_code == 404
    assert client.get("/calendar/" + "x" * 500 + ".ics").status_code == 404


def test_the_access_log_never_contains_the_token() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "GET", "/calendar/s3cr3t-T0ken_x.ics", "1.1", 200),
        None,
    )

    HideCalendarTokens().filter(record)

    assert "s3cr3t" not in record.getMessage()
    assert '"GET /calendar/… HTTP/1.1" 200' in record.getMessage()
