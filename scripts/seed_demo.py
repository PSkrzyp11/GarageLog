"""Demo data: one account with two cars and about two years of history.

    docker compose exec app python -m scripts.seed_demo            # in Docker
    uv run python -m scripts.seed_demo                             # locally
    DEMO_PASSWORD=... uv run python -m scripts.seed_demo --reset   # recreate

The data is fictional (example.com e-mail, "DEMO" plates) and generated deterministically:
the same random seed always gives the same history, dated relative to today so the demo
always looks current. It exercises every feature: partial refuels and a missed one
(consumption), petrol + LPG (separate results), several expense categories (costs),
and overdue / due-soon / planned / done reminders.

The history is simulated (a tank that empties as the car drives), so the numbers obey the
same rules the app enforces: mileage never decreases and consumption is realistic.
"""

import argparse
import datetime as dt
import os
import random
import secrets
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Car,
    FuelEntry,
    FuelType,
    OdometerReading,
    PrimaryFuel,
    Reminder,
    ServiceCategory,
    ServiceEntry,
    User,
)
from app.security import hash_password
from app.timeutils import today as current_day

DEMO_EMAIL = "demo@example.com"
HISTORY_DAYS = 730
RANDOM_SEED = 2026


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Tank:
    """A fuel tank that empties while driving; refuels log what was put back in."""

    fuel: FuelType
    capacity: float
    liters_per_100km: float
    price_per_liter: float
    level: float

    def drive(self, km: float, rng: random.Random) -> None:
        rate = self.liters_per_100km * rng.uniform(0.9, 1.12)  # city vs motorway
        self.level = max(self.level - km * rate / 100, 0.0)


@dataclass
class CarPlan:
    car: Car
    start_km: int
    km_per_day: tuple[float, float]
    tanks: list[Tank]
    refuel_below: dict[FuelType, float]
    partial_share: float  # how often a refuel is not to a full tank


def _simulate(db: Session, plan: CarPlan, start: dt.date, end: dt.date, rng: random.Random) -> int:
    """Daily simulation of driving and refuels; returns the final mileage."""
    km = float(plan.start_km)
    db.add(
        OdometerReading(
            car_id=plan.car.id, date=start, odometer_km=plan.start_km, note="Zakup auta"
        )
    )
    missed_done = False
    pending_missed: set[FuelType] = set()
    day = start
    while day < end:
        day += dt.timedelta(days=1)
        if rng.random() < 0.2:  # not every day is a driving day
            continue
        distance = rng.uniform(*plan.km_per_day) * 1.25
        km += distance
        for tank in plan.tanks:
            tank.drive(distance, rng)
            if tank.level > plan.refuel_below[tank.fuel]:
                continue

            full = rng.random() > plan.partial_share
            liters = tank.capacity - tank.level if full else rng.uniform(15, 25)
            tank.level = min(tank.level + liters, tank.capacity)
            tank.price_per_liter *= rng.uniform(0.98, 1.025)
            liters_d = _money(liters)

            # Once per car, around the middle of the history, a full refuel is not logged:
            # the next logged one is marked "missed previous" (that segment is skipped).
            if not missed_done and full and (day - start).days > HISTORY_DAYS // 2:
                missed_done = True
                pending_missed.add(tank.fuel)
                continue

            db.add(
                FuelEntry(
                    car_id=plan.car.id,
                    date=day,
                    odometer_km=int(km),
                    fuel_type=tank.fuel,
                    liters=liters_d,
                    total_cost_pln=_money(float(liters_d) * tank.price_per_liter),
                    is_full_tank=full,
                    missed_previous=tank.fuel in pending_missed,
                )
            )
            pending_missed.discard(tank.fuel)
    return int(km)


def _mileage_on(db: Session, car: Car, day: dt.date) -> int:
    """Highest logged mileage on or before `day`, so service entries fit the history."""
    values = [
        entry.odometer_km
        for entry in db.scalars(
            select(FuelEntry).where(FuelEntry.car_id == car.id, FuelEntry.date <= day)
        )
    ]
    return max(values, default=0)


def _services(
    db: Session, car: Car, start: dt.date, items: list[tuple[int, ServiceCategory, str, str]]
) -> None:
    """(days after start, category, title, cost); mileage only for workshop visits."""
    workshop = {ServiceCategory.MAINTENANCE, ServiceCategory.REPAIR, ServiceCategory.TIRES}
    for days, category, title, cost in items:
        day = start + dt.timedelta(days=days)
        db.add(
            ServiceEntry(
                car_id=car.id,
                date=day,
                odometer_km=_mileage_on(db, car, day) if category in workshop else None,
                category=category,
                title=title,
                cost_pln=Decimal(cost),
            )
        )


def seed(db: Session, password: str, today: dt.date | None = None) -> User:
    """Create the demo account and its data in `db` (flushes; the caller commits)."""
    today = today or current_day()
    start = today - dt.timedelta(days=HISTORY_DAYS)
    rng = random.Random(RANDOM_SEED)

    user = User(email=DEMO_EMAIL, password_hash=hash_password(password))
    db.add(user)
    db.flush()

    octavia = Car(
        user_id=user.id,
        name="Octavia",
        make="Skoda",
        model="Octavia III Combi",
        production_year=2017,
        registration_number="DEMO 001",
        primary_fuel=PrimaryFuel.DIESEL,
    )
    astra = Car(
        user_id=user.id,
        name="Astra",
        make="Opel",
        model="Astra J",
        production_year=2013,
        registration_number="DEMO 002",
        primary_fuel=PrimaryFuel.PETROL,
        has_lpg=True,
    )
    db.add_all([octavia, astra])
    db.flush()

    octavia_km = _simulate(
        db,
        CarPlan(
            car=octavia,
            start_km=128_400,
            km_per_day=(20, 70),
            tanks=[Tank(FuelType.DIESEL, 50, 5.4, 6.29, 30)],
            refuel_below={FuelType.DIESEL: 9},
            partial_share=0.12,
        ),
        start,
        today,
        rng,
    )
    astra_km = _simulate(
        db,
        CarPlan(
            car=astra,
            start_km=186_200,
            km_per_day=(15, 45),
            tanks=[
                Tank(FuelType.LPG, 40, 9.6, 2.89, 20),
                Tank(FuelType.PETROL, 50, 0.7, 6.49, 40),
            ],
            refuel_below={FuelType.LPG: 7, FuelType.PETROL: 18},
            partial_share=0.1,
        ),
        start,
        today,
        rng,
    )
    db.flush()

    _services(
        db,
        octavia,
        start,
        [
            (12, ServiceCategory.INSURANCE, "OC/AC", "1890.00"),
            (30, ServiceCategory.INSPECTION, "Badanie techniczne", "149.00"),
            (45, ServiceCategory.MAINTENANCE, "Wymiana oleju i filtrów", "649.99"),
            (170, ServiceCategory.TIRES, "Wymiana opon na letnie", "140.00"),
            (215, ServiceCategory.REPAIR, "Klocki i tarcze hamulcowe — przód", "1180.00"),
            (380, ServiceCategory.INSURANCE, "OC/AC", "2049.00"),
            (395, ServiceCategory.INSPECTION, "Badanie techniczne", "149.00"),
            (410, ServiceCategory.MAINTENANCE, "Wymiana oleju i filtrów", "689.00"),
            (420, ServiceCategory.TIRES, "Wymiana opon na zimowe", "140.00"),
            (535, ServiceCategory.TIRES, "Wymiana opon na letnie", "150.00"),
            (600, ServiceCategory.OTHER, "Myjnia i detailing", "350.00"),
        ],
    )
    _services(
        db,
        astra,
        start,
        [
            (20, ServiceCategory.INSURANCE, "OC", "980.00"),
            (60, ServiceCategory.INSPECTION, "Badanie techniczne z LPG", "162.00"),
            (90, ServiceCategory.MAINTENANCE, "Przegląd instalacji LPG", "180.00"),
            (250, ServiceCategory.REPAIR, "Wymiana alternatora", "1250.00"),
            (300, ServiceCategory.MAINTENANCE, "Wymiana oleju i filtrów", "420.00"),
            (390, ServiceCategory.INSURANCE, "OC", "1035.00"),
            (425, ServiceCategory.INSPECTION, "Badanie techniczne z LPG", "162.00"),
            (455, ServiceCategory.MAINTENANCE, "Przegląd instalacji LPG", "190.00"),
            (640, ServiceCategory.MAINTENANCE, "Wymiana oleju i filtrów", "450.00"),
        ],
    )

    db.add_all(
        [
            # Overdue by date.
            Reminder(
                car_id=octavia.id,
                title="Wymiana płynu hamulcowego",
                due_date=today - dt.timedelta(days=9),
            ),
            # Due soon by mileage, with a date far away ("whichever comes first").
            Reminder(
                car_id=octavia.id,
                title="Wymiana oleju i filtrów",
                due_odometer_km=octavia_km + 600,
                due_date=today + dt.timedelta(days=150),
                repeat_months=12,
                repeat_km=15_000,
            ),
            # Planned.
            Reminder(
                car_id=octavia.id,
                title="Wymiana rozrządu",
                due_odometer_km=octavia_km + 25_000,
                notes="Zalecenie producenta: co 180 000 km lub 6 lat.",
            ),
            # Due soon by date.
            Reminder(
                car_id=astra.id,
                title="Badanie techniczne z LPG",
                due_date=today + dt.timedelta(days=18),
                repeat_months=12,
            ),
            Reminder(
                car_id=astra.id,
                title="Przegląd instalacji LPG",
                due_odometer_km=astra_km + 4_000,
            ),
            # Already done.
            Reminder(
                car_id=astra.id,
                title="Wymiana opon na zimowe",
                due_date=today - dt.timedelta(days=20),
                completed_at=dt.datetime.combine(
                    today - dt.timedelta(days=22), dt.time(10), tzinfo=dt.UTC
                ),
            ),
        ]
    )
    db.flush()
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reset", action="store_true", help="delete and recreate the demo user")
    args = parser.parse_args()

    password = os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(12)
    engine = create_engine(get_settings().database_url)
    with Session(engine) as db:
        existing = db.scalars(select(User).where(User.email == DEMO_EMAIL)).one_or_none()
        if existing is not None:
            if not args.reset:
                sys.exit(f"{DEMO_EMAIL} already exists; run with --reset to recreate it.")
            db.execute(delete(User).where(User.id == existing.id))  # cascades to all data
        seed(db, password)
        db.commit()

    print(f"Demo account: {DEMO_EMAIL}")
    if "DEMO_PASSWORD" not in os.environ:
        print(f"Password (shown once, not stored anywhere): {password}")


if __name__ == "__main__":
    main()
