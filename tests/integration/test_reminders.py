from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.formatting import format_km
from app.models import Reminder
from app.stats import add_months
from app.timeutils import today
from tests.integration.helpers import (
    OTHER_EMAIL,
    add_car,
    add_fuel_entry,
    add_reminder,
    count,
    login,
    logout,
    post_form,
    register,
    reminder_form,
)


@pytest.fixture
def car_id(client: TestClient) -> int:
    """A logged-in user with a car added today at 120 000 km."""
    register(client)
    return add_car(client, name="Golf", initial_odometer_km="120000", has_lpg="")


def in_days(days: int) -> str:
    return (today() + timedelta(days=days)).isoformat()


def reminders_page(client: TestClient, car_id: int) -> str:
    return client.get(f"/cars/{car_id}/reminders").text


def test_reminder_is_listed_with_status_and_due_text(client: TestClient, car_id: int) -> None:
    add_reminder(client, car_id, title="Przegląd", due_date=in_days(12))

    page = reminders_page(client, car_id)

    assert "Przegląd" in page
    assert "Wkrótce" in page
    assert "za 12 dni" in page


def test_form_without_date_or_mileage_shows_an_error(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    url = f"/cars/{car_id}/reminders/new"

    response = post_form(client, url, reminder_form(due_date=""), url)

    assert response.status_code == 422
    assert "Podaj termin: datę, przebieg albo oba" in response.text
    assert count(db_session, Reminder) == 0


def test_active_reminders_are_sorted_by_urgency(client: TestClient, car_id: int) -> None:
    add_reminder(client, car_id, title="Za rok", due_date=in_days(365))
    add_reminder(client, car_id, title="Zaległe", due_date=in_days(-5))
    add_reminder(client, car_id, title="Za tydzień", due_date=in_days(7))

    page = reminders_page(client, car_id)

    assert page.index("Zaległe</a>") < page.index("Za tydzień") < page.index("Za rok")


def test_refuel_can_make_a_mileage_reminder_overdue(client: TestClient, car_id: int) -> None:
    add_reminder(client, car_id, title="Olej", due_date="", due_odometer_km="122000")
    assert "Zaplanowane" in reminders_page(client, car_id)  # 2 000 km left

    add_fuel_entry(client, car_id, date=today().isoformat(), odometer_km="122100")

    page = reminders_page(client, car_id)
    assert "Zaległe" in page
    assert "100 km po terminie" in page


def test_dashboard_shows_only_reminders_needing_attention(client: TestClient, car_id: int) -> None:
    add_reminder(client, car_id, title="Pilne OC", due_date=in_days(-1))
    add_reminder(client, car_id, title="Wymiana opon", due_date=in_days(20))
    add_reminder(client, car_id, title="Rozrząd", due_date=in_days(300))

    dashboard = client.get("/").text

    assert "Do zrobienia" in dashboard
    assert "Pilne OC" in dashboard
    assert "Wymiana opon" in dashboard
    assert "Rozrząd" not in dashboard
    assert "Golf" in dashboard[dashboard.index("Do zrobienia") :]  # the car is named


def test_completing_from_the_dashboard_returns_there_and_hides_it(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    reminder_id = add_reminder(client, car_id, title="Pilne OC", due_date=in_days(-1))

    response = post_form(
        client,
        f"/cars/{car_id}/reminders/{reminder_id}/complete",
        {"return_to": "dashboard"},
        form_page="/",
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("/")
    assert "Pilne OC" not in client.get("/").text
    reminder = db_session.get(Reminder, reminder_id)
    db_session.refresh(reminder)
    assert reminder.completed_at is not None


def test_return_to_only_accepts_known_pages(client: TestClient, car_id: int) -> None:
    reminder_id = add_reminder(client, car_id)

    response = post_form(
        client,
        f"/cars/{car_id}/reminders/{reminder_id}/complete",
        {"return_to": "https://evil.example.com"},
        form_page="/",
    )

    assert response.headers["location"].endswith(f"/cars/{car_id}/reminders")


def test_completed_reminder_moves_to_done_and_can_be_reopened(
    client: TestClient, car_id: int
) -> None:
    reminder_id = add_reminder(client, car_id, title="Przegląd")
    base = f"/cars/{car_id}/reminders/{reminder_id}"
    post_form(client, f"{base}/complete", {}, form_page=f"/cars/{car_id}/reminders")

    page = reminders_page(client, car_id)
    assert "Brak aktywnych przypomnień." in page
    assert "Ostatnio wykonane" in page
    assert f"Wykonane {today().strftime('%d.%m.%Y')}" in page

    post_form(client, f"{base}/reopen", {}, form_page=f"/cars/{car_id}/reminders")

    assert "Ostatnio wykonane" not in reminders_page(client, car_id)


def test_edit_and_delete_reminder(client: TestClient, db_session: Session, car_id: int) -> None:
    reminder_id = add_reminder(client, car_id, title="Olej", due_date="2027-01-01")
    edit = f"/cars/{car_id}/reminders/{reminder_id}/edit"
    assert 'value="2027-01-01"' in client.get(edit).text

    post_form(client, edit, reminder_form(title="Olej i filtry", due_odometer_km="135000"), edit)
    assert "Olej i filtry" in reminders_page(client, car_id)

    delete = f"/cars/{car_id}/reminders/{reminder_id}/delete"
    post_form(client, delete, {}, delete)
    assert count(db_session, Reminder) == 0


def test_deleting_car_removes_its_reminders(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    add_reminder(client, car_id)
    url = f"/cars/{car_id}/delete"
    assert "przypomnienia: 1" in client.get(url).text

    post_form(client, url, {}, url)

    assert count(db_session, Reminder) == 0


# --- Recurring reminders ----------------------------------------------------------------


def complete(client: TestClient, car_id: int, reminder_id: int) -> None:
    url = f"/cars/{car_id}/reminders/{reminder_id}/complete"
    assert post_form(client, url, {}, form_page=f"/cars/{car_id}/reminders").status_code == 303


def reopen(client: TestClient, car_id: int, reminder_id: int) -> None:
    url = f"/cars/{car_id}/reminders/{reminder_id}/reopen"
    assert post_form(client, url, {}, form_page=f"/cars/{car_id}/reminders").status_code == 303


def next_occurrence(db: Session, reminder_id: int) -> Reminder:
    return db.scalars(select(Reminder).where(Reminder.created_from_id == reminder_id)).one()


def test_recurring_reminder_shows_how_it_repeats(client: TestClient, car_id: int) -> None:
    add_reminder(client, car_id, repeat_months="12", repeat_km="15 000")

    assert f"Powtarza się co rok lub {format_km(15_000)}" in reminders_page(client, car_id)


def test_completing_a_recurring_reminder_creates_the_next_one(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    # Done 3 days late: the next one counts from today and the current 120 000 km.
    reminder_id = add_reminder(
        client, car_id, title="Olej", due_date=in_days(-3), repeat_months="12", repeat_km="15000"
    )

    complete(client, car_id, reminder_id)

    following = next_occurrence(db_session, reminder_id)
    assert following.title == "Olej"
    assert following.due_date == add_months(today(), 12)
    assert following.due_odometer_km == 135_000
    assert (following.repeat_months, following.repeat_km) == (12, 15_000)
    assert following.completed_at is None
    page = reminders_page(client, car_id)
    assert f"do {following.due_date.strftime('%d.%m.%Y')} lub do {format_km(135_000)}" in page
    assert "Ostatnio wykonane" in page


def test_completing_twice_creates_only_one_next_occurrence(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    reminder_id = add_reminder(client, car_id, repeat_months="12")

    complete(client, car_id, reminder_id)
    complete(client, car_id, reminder_id)  # e.g. a double click without JavaScript

    assert count(db_session, Reminder) == 2


def test_completing_a_one_off_reminder_creates_nothing(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    reminder_id = add_reminder(client, car_id)

    complete(client, car_id, reminder_id)

    assert count(db_session, Reminder) == 1


def test_reopening_removes_the_next_occurrence(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    reminder_id = add_reminder(client, car_id, repeat_months="12")
    complete(client, car_id, reminder_id)

    reopen(client, car_id, reminder_id)

    assert count(db_session, Reminder) == 1
    reminder = db_session.get(Reminder, reminder_id)
    db_session.refresh(reminder)
    assert reminder.completed_at is None


def test_reopening_keeps_a_next_occurrence_that_was_already_done(
    client: TestClient, db_session: Session, car_id: int
) -> None:
    first_id = add_reminder(client, car_id, repeat_months="12")
    complete(client, car_id, first_id)
    complete(client, car_id, next_occurrence(db_session, first_id).id)

    reopen(client, car_id, first_id)

    # The first one is active again; the second stays done, with its own next occurrence.
    assert count(db_session, Reminder) == 3


def test_edit_form_keeps_the_repeat_interval(client: TestClient, car_id: int) -> None:
    reminder_id = add_reminder(client, car_id, repeat_months="6", repeat_km="10000")

    page = client.get(f"/cars/{car_id}/reminders/{reminder_id}/edit").text

    assert 'name="repeat_months"' in page and 'value="6"' in page
    assert 'value="10000"' in page


# --- Calendar file (.ics) ---------------------------------------------------------------


def calendar_lines(response: Response) -> list[str]:
    return response.content.decode().replace("\r\n ", "").split("\r\n")


def test_car_calendar_has_active_reminders_with_a_date(client: TestClient, car_id: int) -> None:
    dated = add_reminder(client, car_id, title="OC", due_date="2027-01-15", notes="Polisa PZU")
    add_reminder(client, car_id, title="Rozrząd", due_date="", due_odometer_km="180000")
    done = add_reminder(client, car_id, title="Opony", due_date="2026-11-01")
    complete(client, car_id, done)

    response = client.get(f"/cars/{car_id}/reminders/calendar.ics")

    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="garagelog-golf-przypomnienia.ics"'
    )
    assert response.headers["cache-control"] == "private, no-store"
    lines = calendar_lines(response)
    assert lines.count("BEGIN:VEVENT") == 1  # no date: no event; done: not in the file
    assert f"UID:garagelog-reminder-{dated}" in lines
    assert "DTSTART;VALUE=DATE:20270115" in lines
    assert "SUMMARY:Golf: OC" in lines
    # A line break inside a text value is written as the two characters "\n".
    assert "DESCRIPTION:Termin: do 15.01.2027\\nPolisa PZU" in lines


def test_all_cars_calendar_has_only_the_users_own_reminders(
    client: TestClient, car_id: int
) -> None:
    other_car = add_car(client, name="Astra", initial_odometer_km="50000", has_lpg="")
    add_reminder(client, car_id, title="OC Golfa", due_date="2027-01-15")
    add_reminder(client, other_car, title="OC Astry", due_date="2027-02-01")
    logout(client)
    register(client, email=OTHER_EMAIL)
    stranger_car = add_car(client, name="Cudze", initial_odometer_km="1000", has_lpg="")
    add_reminder(client, stranger_car, title="Cudze OC", due_date="2027-03-01")
    logout(client)
    login(client)

    lines = calendar_lines(client.get("/reminders.ics"))

    assert "SUMMARY:Golf: OC Golfa" in lines
    assert "SUMMARY:Astra: OC Astry" in lines
    assert not any("Cudze" in line for line in lines)


def test_all_cars_calendar_needs_login(client: TestClient) -> None:
    response = client.get("/reminders.ics", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")
