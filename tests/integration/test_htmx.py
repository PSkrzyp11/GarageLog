"""HTMX: fragments for HTMX requests, full pages otherwise (progressive enhancement)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Reminder, ServiceEntry
from app.timeutils import today
from tests.integration.helpers import (
    add_car,
    add_reading,
    add_reminder,
    add_service_entry,
    count,
    csrf_token_from,
    register,
)

HTMX = {"HX-Request": "true"}


@pytest.fixture
def car_id(client: TestClient) -> int:
    register(client)
    return add_car(client, name="Golf", initial_odometer_km="120000", has_lpg="")


def htmx_post(client: TestClient, url: str, form_page: str, **data: str) -> str:
    token = csrf_token_from(client, form_page)
    response = client.post(url, data=data | {"csrf_token": token}, headers=HTMX)
    assert response.status_code == 200, response.text
    return response.text


# --- Filters return fragments -----------------------------------------------------------


def test_history_filter_returns_only_the_timeline_for_htmx(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id, title="Serwis 2024", date="2024-04-04")

    fragment = client.get(f"/cars/{car_id}?kind=service", headers=HTMX)

    assert fragment.text.lstrip().startswith('<div id="timeline"')
    assert "Serwis 2024" in fragment.text
    assert "<html" not in fragment.text
    # The same URL returns two kinds of responses; caches must not mix them up.
    assert "HX-Request" in fragment.headers["vary"]


def test_same_url_without_htmx_returns_the_full_page(client: TestClient, car_id: int) -> None:
    page = client.get(f"/cars/{car_id}?kind=service").text

    assert "<html" in page
    assert '<div id="timeline"' in page


def test_back_button_history_restore_gets_the_full_page(client: TestClient, car_id: int) -> None:
    headers = HTMX | {"HX-History-Restore-Request": "true"}

    assert "<html" in client.get(f"/cars/{car_id}", headers=headers).text


def test_cost_period_returns_only_the_summary_for_htmx(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id, cost_pln="111", date=f"{today().year}-01-01")

    fragment = client.get(f"/cars/{car_id}/costs?period=year", headers=HTMX).text

    assert fragment.lstrip().startswith('<div id="cost-summary"')
    assert "111,00 zł" in fragment
    assert "<html" not in fragment


# --- Actions in place -------------------------------------------------------------------


def test_marking_a_reminder_done_returns_the_updated_card(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    reminder_id = add_reminder(client, car_id, title="Przegląd")

    fragment = htmx_post(
        client,
        f"/cars/{car_id}/reminders/{reminder_id}/complete",
        form_page=f"/cars/{car_id}/reminders",
    )

    assert fragment.lstrip().startswith('<li class="card reminder reminder-done"')
    assert "Przywróć" in fragment
    reminder = db_session.get(Reminder, reminder_id)
    db_session.refresh(reminder)
    assert reminder.completed_at is not None


def test_dashboard_card_keeps_the_car_name_and_returns_to_the_dashboard(
    client: TestClient, car_id: int
) -> None:
    reminder_id = add_reminder(client, car_id, title="OC", due_date=today().isoformat())

    fragment = htmx_post(
        client,
        f"/cars/{car_id}/reminders/{reminder_id}/complete",
        form_page="/",
        return_to="dashboard",
    )

    assert "Golf" in fragment
    assert 'name="return_to" value="dashboard"' in fragment


def test_inline_delete_removes_the_row_and_refreshes_mileage(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    reading_id = add_reading(client, car_id, date=today().isoformat(), odometer_km="125000")

    fragment = htmx_post(
        client, f"/cars/{car_id}/odometer/{reading_id}/delete", form_page=f"/cars/{car_id}"
    )

    # Nothing for the row itself (it disappears), only the out-of-band mileage update.
    assert fragment.lstrip().startswith('<dd id="current-odometer" hx-swap-oob="true">')
    assert "120 000 km" in fragment


def test_inline_delete_without_javascript_still_redirects(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    entry_id = add_service_entry(client, car_id)
    token = csrf_token_from(client, f"/cars/{car_id}")

    response = client.post(
        f"/cars/{car_id}/service/{entry_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert count(db_session, ServiceEntry) == 0


def test_timeline_rows_offer_inline_delete_for_every_kind(client: TestClient, car_id: int) -> None:
    add_service_entry(client, car_id)

    page = client.get(f"/cars/{car_id}").text

    assert page.count('class="row-delete"') == 2  # the service entry and the initial reading
    assert 'hx-target="closest li"' in page


# --- Page shell -------------------------------------------------------------------------


def test_htmx_is_loaded_from_our_own_origin_with_a_safe_config(client: TestClient) -> None:
    page = client.get("/login").text

    assert '<script src="http://testserver/static/js/htmx.min.js?v=' in page
    assert '"allowEval": false' in page
    assert '"historyCacheSize": 0' in page
    assert "<script>" not in page  # no inline scripts (Content-Security-Policy)


def test_skip_link_points_to_main_content(client: TestClient) -> None:
    page = client.get("/login").text

    assert '<a class="skip-link" href="#content">' in page
    assert '<main class="container" id="content"' in page
