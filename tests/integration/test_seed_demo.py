"""The demo data must obey the app's own rules, or the demo would show nonsense."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Car, FuelEntry, ServiceEntry
from app.odometer import find_conflict
from app.services import costs as costs_service
from app.services import reminders as reminders_service
from app.services.entries import odometer_points
from app.stats import Period, ReminderStatus
from scripts.seed_demo import DEMO_EMAIL, seed

TODAY = date(2026, 10, 22)


@pytest.fixture
def demo(db_session: Session) -> dict[str, Car]:
    user = seed(db_session, "demo-password-for-tests", today=TODAY)
    cars = db_session.scalars(select(Car).where(Car.user_id == user.id)).all()
    assert user.email == DEMO_EMAIL
    return {car.name: car for car in cars}


def test_two_cars_one_with_lpg(demo: dict[str, Car]) -> None:
    assert set(demo) == {"Octavia", "Astra"}
    assert demo["Astra"].has_lpg


def test_mileage_never_decreases_with_the_date(db_session: Session, demo: dict[str, Car]) -> None:
    for car in demo.values():
        points = odometer_points(db_session, car)
        for index, point in enumerate(points):
            others = points[:index] + points[index + 1 :]
            assert find_conflict(others, point.date, point.odometer_km) is None, point


def test_nothing_is_dated_in_the_future(db_session: Session, demo: dict[str, Car]) -> None:
    for model in (FuelEntry, ServiceEntry):
        assert all(day <= TODAY for day in db_session.scalars(select(model.date)))


def test_consumption_is_realistic_for_every_fuel(
    db_session: Session, demo: dict[str, Car], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(costs_service, "today", lambda: TODAY)
    ranges = {"diesel": (4.5, 7.0), "lpg": (8.0, 12.0), "petrol": (0.3, 1.5)}

    results = {
        fuel.fuel_type: fuel.liters_per_100km
        for car in demo.values()
        for fuel in costs_service.car_consumption(db_session, car, Period.ALL).by_fuel
    }

    assert set(results) == set(ranges)
    for fuel_type, value in results.items():
        low, high = ranges[fuel_type]
        assert value is not None and low <= value <= high, (fuel_type, value)


def test_each_car_has_one_missed_refuel(db_session: Session, demo: dict[str, Car]) -> None:
    for car in demo.values():
        missed = db_session.scalars(
            select(FuelEntry).where(FuelEntry.car_id == car.id, FuelEntry.missed_previous)
        ).all()
        assert len(missed) == 1, car.name


def test_costs_and_cost_per_km_are_available(
    db_session: Session, demo: dict[str, Car], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(costs_service, "today", lambda: TODAY)

    for car in demo.values():
        summary = costs_service.car_cost_summary(db_session, car, Period.ALL)
        assert summary.total_pln > 0
        assert summary.cost_per_km_pln is not None
        assert len(summary.by_category) >= 4


def test_reminders_cover_every_status(
    db_session: Session, demo: dict[str, Car], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reminders_service, "today", lambda: TODAY)

    statuses = set()
    for car in demo.values():
        listing = reminders_service.car_reminders(db_session, car)
        statuses |= {view.state.status for view in listing.active + listing.done}

    assert statuses == {
        ReminderStatus.OVERDUE,
        ReminderStatus.DUE_SOON,
        ReminderStatus.PLANNED,
        ReminderStatus.DONE,
    }


def test_seed_is_deterministic(db_session: Session) -> None:
    def fingerprint() -> list[tuple]:
        return sorted(
            (e.date, e.odometer_km, str(e.liters))
            for e in db_session.scalars(select(FuelEntry)).all()
        )

    seed(db_session, "x" * 12, today=TODAY)
    first = fingerprint()
    db_session.rollback()  # back to the empty database (savepoint)

    seed(db_session, "x" * 12, today=TODAY)
    assert fingerprint() == first
