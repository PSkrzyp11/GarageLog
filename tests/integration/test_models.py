from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Car,
    FuelEntry,
    FuelType,
    OdometerReading,
    PrimaryFuel,
    Receipt,
    ServiceCategory,
    ServiceEntry,
    User,
    UserSession,
)


def make_user(email: str = "jan@example.com") -> User:
    return User(email=email, password_hash="not-a-real-hash")


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("liters", Decimal("0"), "ck_fuel_entries_liters_positive"),
        ("total_cost_pln", Decimal("0"), "ck_fuel_entries_total_cost_pln_positive"),
        ("odometer_km", -1, "ck_fuel_entries_odometer_km_non_negative"),
    ],
)
def test_fuel_entry_values_are_checked_by_the_database(
    db_session: Session, field: str, value: object, constraint: str
) -> None:
    user = make_user()
    db_session.add(user)
    db_session.flush()
    car = Car(user_id=user.id, name="Golf", primary_fuel=PrimaryFuel.PETROL)
    db_session.add(car)
    db_session.flush()
    entry = FuelEntry(
        car_id=car.id,
        date=date(2025, 1, 1),
        odometer_km=1000,
        fuel_type=FuelType.PETROL,
        liters=Decimal("40"),
        total_cost_pln=Decimal("250"),
        is_full_tank=True,
    )
    setattr(entry, field, value)
    db_session.add(entry)

    with pytest.raises(IntegrityError, match=constraint):
        db_session.commit()


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


def make_car(user: User, name: str = "Golf") -> Car:
    return Car(user_id=user.id, name=name, primary_fuel=PrimaryFuel.PETROL)


def test_car_primary_fuel_is_limited_by_check_constraint(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.flush()

    # Bypass the ORM enum to write a value the application would never produce.
    with pytest.raises(IntegrityError, match="ck_cars_primary_fuel_values"):
        db_session.execute(
            text("INSERT INTO cars (user_id, name, primary_fuel) VALUES (:user_id, 'X', 'lpg')"),
            {"user_id": user.id},
        )


def test_car_production_year_range_is_checked(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.flush()
    car = make_car(user)
    car.production_year = 1800
    db_session.add(car)

    with pytest.raises(IntegrityError, match="ck_cars_production_year_range"):
        db_session.commit()


def test_odometer_reading_cannot_be_negative(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.flush()
    car = make_car(user)
    db_session.add(car)
    db_session.flush()
    db_session.add(OdometerReading(car_id=car.id, date=date(2026, 1, 1), odometer_km=-1))

    with pytest.raises(IntegrityError, match="ck_odometer_readings_odometer_km_non_negative"):
        db_session.commit()


def test_deleting_user_deletes_their_cars_and_readings(db_session: Session) -> None:
    user = make_user()
    db_session.add(user)
    db_session.flush()
    car = make_car(user)
    db_session.add(car)
    db_session.flush()
    db_session.add(OdometerReading(car_id=car.id, date=date(2026, 1, 1), odometer_km=1000))
    db_session.commit()

    db_session.delete(user)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Car)) == 0
    assert db_session.scalar(select(func.count()).select_from(OdometerReading)) == 0


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


@pytest.mark.parametrize("parents", ["none", "both"])
def test_a_receipt_belongs_to_exactly_one_entry(db_session: Session, parents: str) -> None:
    user = make_user()
    db_session.add(user)
    db_session.flush()
    car = Car(user_id=user.id, name="Golf", primary_fuel=PrimaryFuel.PETROL)
    db_session.add(car)
    db_session.flush()
    fuel = FuelEntry(
        car_id=car.id,
        date=date(2025, 1, 1),
        odometer_km=1000,
        fuel_type=FuelType.PETROL,
        liters=Decimal("40"),
        total_cost_pln=Decimal("250"),
        is_full_tank=True,
    )
    service = ServiceEntry(
        car_id=car.id,
        date=date(2025, 1, 2),
        category=ServiceCategory.REPAIR,
        title="Naprawa",
        cost_pln=Decimal("100"),
    )
    db_session.add_all([fuel, service])
    db_session.flush()
    owners = {"none": {}, "both": {"fuel_entry_id": fuel.id, "service_entry_id": service.id}}
    db_session.add(Receipt(content_type="application/pdf", data=b"%PDF-", **owners[parents]))

    with pytest.raises(IntegrityError, match="ck_receipts_one_entry"):
        db_session.commit()
