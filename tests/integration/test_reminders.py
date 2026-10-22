from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Reminder
from app.timeutils import today
from tests.integration.helpers import (
    add_car,
    add_fuel_entry,
    add_reminder,
    count,
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
