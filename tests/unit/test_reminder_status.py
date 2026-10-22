from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.schemas import ReminderForm, form_errors, parse_form
from app.stats import ReminderStatus, describe_due, reminder_state

TODAY = date(2026, 10, 22)


def status(
    due_date: date | None = None,
    due_km: int | None = None,
    current_km: int | None = None,
    completed: bool = False,
) -> ReminderStatus:
    return reminder_state(due_date, due_km, completed, TODAY, current_km).status


# --- By date ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (-1, ReminderStatus.OVERDUE),
        (0, ReminderStatus.DUE_SOON),  # due today: not overdue yet
        (30, ReminderStatus.DUE_SOON),
        (31, ReminderStatus.PLANNED),
    ],
)
def test_status_by_date(days: int, expected: ReminderStatus) -> None:
    assert status(due_date=TODAY + timedelta(days=days)) == expected


# --- By mileage -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current_km", "expected"),
    [
        (130_100, ReminderStatus.OVERDUE),
        (130_000, ReminderStatus.OVERDUE),  # mileage reached
        (129_000, ReminderStatus.DUE_SOON),  # 1000 km left
        (128_999, ReminderStatus.PLANNED),
    ],
)
def test_status_by_mileage(current_km: int, expected: ReminderStatus) -> None:
    assert status(due_km=130_000, current_km=current_km) == expected


def test_mileage_only_reminder_without_any_mileage_says_so() -> None:
    assert status(due_km=130_000, current_km=None) == ReminderStatus.NO_MILEAGE


# --- Both: whichever comes first --------------------------------------------------------


def test_plan_acceptance_example_mileage_passed_before_the_date() -> None:
    """'By 01.06 or by 130 000 km' at 130 100 km is overdue although the date hasn't passed."""
    assert (
        status(due_date=date(2027, 6, 1), due_km=130_000, current_km=130_100)
        == ReminderStatus.OVERDUE
    )


def test_date_passed_while_mileage_is_far() -> None:
    assert (
        status(due_date=TODAY - timedelta(days=3), due_km=200_000, current_km=120_000)
        == ReminderStatus.OVERDUE
    )


def test_the_closer_condition_makes_it_due_soon() -> None:
    far_date = TODAY + timedelta(days=200)
    assert status(due_date=far_date, due_km=120_500, current_km=120_000) == ReminderStatus.DUE_SOON


def test_both_conditions_without_mileage_fall_back_to_the_date() -> None:
    far_date = TODAY + timedelta(days=200)
    assert status(due_date=far_date, due_km=130_000, current_km=None) == ReminderStatus.PLANNED


def test_completed_reminder_is_done_regardless_of_dates() -> None:
    assert status(due_date=TODAY - timedelta(days=100), completed=True) == ReminderStatus.DONE


# --- Ordering and descriptions ----------------------------------------------------------


def test_most_urgent_first() -> None:
    states = {
        "planned": reminder_state(TODAY + timedelta(days=90), None, False, TODAY, None),
        "soon_by_km": reminder_state(None, 120_900, False, TODAY, 120_000),  # 900 km ≈ 27 days
        "soon_by_date": reminder_state(TODAY + timedelta(days=5), None, False, TODAY, None),
        "overdue": reminder_state(TODAY - timedelta(days=1), None, False, TODAY, None),
    }

    ordered = sorted(states, key=lambda name: states[name].sort_key)

    assert ordered == ["overdue", "soon_by_date", "soon_by_km", "planned"]


@pytest.mark.parametrize(
    ("days", "km_left", "expected"),
    [
        (12, None, ["za 12 dni"]),
        (1, None, ["za 1 dzień"]),
        (0, None, ["dziś"]),
        (-3, None, ["3 dni po terminie"]),
        (None, 800, ["za 800 km"]),
        (None, 0, ["przebieg osiągnięty"]),
        (None, -100, ["100 km po terminie"]),
        (40, 500, ["za 40 dni", "za 500 km"]),
    ],
)
def test_describe_due(days: int | None, km_left: int | None, expected: list[str]) -> None:
    due_date = TODAY + timedelta(days=days) if days is not None else None
    due_km = 100_000 + km_left if km_left is not None else None
    state = reminder_state(due_date, due_km, False, TODAY, 100_000 if km_left is not None else None)

    assert describe_due(state) == expected


# --- Form -------------------------------------------------------------------------------

FORM = {"title": "Wymiana oleju", "due_date": "", "due_odometer_km": "", "notes": ""}


def test_form_needs_a_date_or_a_mileage() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_form(ReminderForm, FORM)

    assert form_errors(exc_info.value) == {
        "form": "Podaj termin: datę, przebieg albo oba (liczy się to, co pierwsze)."
    }


def test_form_accepts_a_past_or_future_date_and_a_mileage() -> None:
    past = parse_form(ReminderForm, FORM | {"due_date": "2020-01-01"})
    future = parse_form(ReminderForm, FORM | {"due_date": "2031-05-05"})
    by_km = parse_form(ReminderForm, FORM | {"due_odometer_km": "135 000"})

    assert past.due_date == date(2020, 1, 1)
    assert future.due_date == date(2031, 5, 5)
    assert by_km.due_odometer_km == 135_000


def test_form_requires_a_title() -> None:
    with pytest.raises(ValidationError) as exc_info:
        parse_form(ReminderForm, FORM | {"title": " ", "due_date": "2027-01-01"})

    assert list(form_errors(exc_info.value)) == ["title"]
