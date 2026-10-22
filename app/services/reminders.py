"""Reminders: storage in the database, status from app/stats.py.

Functions here only flush; the route commits. The car and reminder passed in were already
checked for ownership by the dependencies in app/deps.py.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Car, Reminder, User
from app.schemas import ReminderForm
from app.services import cars as cars_service
from app.stats import ReminderState, ReminderStatus, describe_due, reminder_state
from app.timeutils import today

# Shown on the dashboard: what needs attention now.
NEEDS_ATTENTION = (ReminderStatus.OVERDUE, ReminderStatus.DUE_SOON)
RECENTLY_DONE_LIMIT = 10


@dataclass(frozen=True)
class ReminderView:
    reminder: Reminder
    car: Car
    state: ReminderState

    @property
    def due_parts(self) -> list[str]:
        return describe_due(self.state)


def _view(reminder: Reminder, car: Car, current_km: int | None, day: dt.date) -> ReminderView:
    state = reminder_state(
        reminder.due_date,
        reminder.due_odometer_km,
        reminder.completed_at is not None,
        day,
        current_km,
    )
    return ReminderView(reminder, car, state)


@dataclass(frozen=True)
class CarReminders:
    active: list[ReminderView]  # most urgent first
    done: list[ReminderView]  # most recently completed first


def car_reminders(db: Session, car: Car) -> CarReminders:
    current_km = cars_service.current_odometer_km(db, car)
    day = today()
    active = [
        _view(reminder, car, current_km, day)
        for reminder in db.scalars(
            select(Reminder).where(Reminder.car_id == car.id, Reminder.completed_at.is_(None))
        )
    ]
    done = [
        _view(reminder, car, current_km, day)
        for reminder in db.scalars(
            select(Reminder)
            .where(Reminder.car_id == car.id, Reminder.completed_at.is_not(None))
            .order_by(Reminder.completed_at.desc())
            .limit(RECENTLY_DONE_LIMIT)
        )
    ]
    return CarReminders(sorted(active, key=lambda view: view.state.sort_key), done)


def reminders_needing_attention(db: Session, user: User) -> list[ReminderView]:
    """Overdue and due-soon reminders of all the user's cars, most urgent first."""
    summaries = {summary.car.id: summary for summary in cars_service.list_cars(db, user)}
    day = today()
    views = [
        _view(reminder, summaries[reminder.car_id].car, summaries[reminder.car_id].odometer_km, day)
        for reminder in db.scalars(
            select(Reminder).where(Reminder.car_id.in_(summaries), Reminder.completed_at.is_(None))
        )
    ]
    urgent = [view for view in views if view.state.status in NEEDS_ATTENTION]
    return sorted(urgent, key=lambda view: view.state.sort_key)


def create_reminder(db: Session, car: Car, form: ReminderForm) -> Reminder:
    reminder = Reminder(car_id=car.id, **form.model_dump())
    db.add(reminder)
    db.flush()
    return reminder


def update_reminder(db: Session, reminder: Reminder, form: ReminderForm) -> None:
    for field, value in form.model_dump().items():
        setattr(reminder, field, value)
    db.flush()


def set_completed(db: Session, reminder: Reminder, completed: bool) -> None:
    reminder.completed_at = dt.datetime.now(dt.UTC) if completed else None
    db.flush()


def delete_reminder(db: Session, reminder: Reminder) -> None:
    db.delete(reminder)
    db.flush()
