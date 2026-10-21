"""Loads a car's expenses from the database and summarizes them with app/stats.py.

Nothing is cached or stored: summaries are calculated from the entries on every request, so
editing or deleting an entry is reflected immediately and nothing can get out of sync.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session

from app.models import Car, FuelEntry, ServiceCategory, ServiceEntry, User
from app.services.entries import odometer_points
from app.stats import FUEL, CostSummary, Expense, Period, summarize_costs
from app.timeutils import today


def category_label(category: str) -> str:
    return "Paliwo" if category == FUEL else ServiceCategory(category).label


def car_expenses(db: Session, car: Car) -> list[Expense]:
    expenses = [
        Expense(entry.date, entry.cost_pln, entry.category.value)
        for entry in db.scalars(select(ServiceEntry).where(ServiceEntry.car_id == car.id))
    ]
    expenses += [
        Expense(entry.date, entry.total_cost_pln, FUEL)
        for entry in db.scalars(select(FuelEntry).where(FuelEntry.car_id == car.id))
    ]
    return expenses


def car_cost_summary(db: Session, car: Car, period: Period) -> CostSummary:
    return summarize_costs(car_expenses(db, car), odometer_points(db, car), period, today())


def costs_since(db: Session, user: User, start: dt.date) -> dict[int, Decimal]:
    """Total cost per car of the user from `start` until today, in one query (for the dashboard).

    Same definition as the "total cost" in app/stats.py: refuels plus service entries.
    """
    amounts = union_all(
        select(ServiceEntry.car_id, ServiceEntry.cost_pln.label("amount")).where(
            ServiceEntry.date >= start
        ),
        select(FuelEntry.car_id, FuelEntry.total_cost_pln.label("amount")).where(
            FuelEntry.date >= start
        ),
    ).subquery()
    rows = db.execute(
        select(amounts.c.car_id, func.sum(amounts.c.amount))
        .join(Car, Car.id == amounts.c.car_id)
        .where(Car.user_id == user.id)
        .group_by(amounts.c.car_id)
    ).all()
    return {car_id: total for car_id, total in rows}
