"""Reminders: storage in the database, status from app/stats.py.

Functions here only flush; the route commits. The car and reminder passed in were already
checked for ownership by the dependencies in app/deps.py.
"""

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.formatting import format_date, format_km
from app.ics import CalendarEvent, calendar
from app.models import Car, Reminder, User
from app.schemas import ReminderForm
from app.services import cars as cars_service
from app.stats import (
    ReminderState,
    ReminderStatus,
    describe_due,
    describe_repeat,
    next_due,
    reminder_state,
)
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

    @property
    def repeat_text(self) -> str:
        return describe_repeat(self.reminder.repeat_months, self.reminder.repeat_km)


def _view(reminder: Reminder, car: Car, current_km: int | None, day: dt.date) -> ReminderView:
    state = reminder_state(
        reminder.due_date,
        reminder.due_odometer_km,
        reminder.completed_at is not None,
        day,
        current_km,
    )
    return ReminderView(reminder, car, state)


def reminder_view(db: Session, reminder: Reminder, car: Car) -> ReminderView:
    """A single reminder with its current status (e.g. to re-render it after an action)."""
    return _view(reminder, car, cars_service.current_odometer_km(db, car), today())


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


def active_reminders(db: Session, user: User) -> list[ReminderView]:
    """Active reminders of all the user's cars, most urgent first."""
    summaries = {summary.car.id: summary for summary in cars_service.list_cars(db, user)}
    day = today()
    views = [
        _view(reminder, summaries[reminder.car_id].car, summaries[reminder.car_id].odometer_km, day)
        for reminder in db.scalars(
            select(Reminder).where(Reminder.car_id.in_(summaries), Reminder.completed_at.is_(None))
        )
    ]
    return sorted(views, key=lambda view: view.state.sort_key)


def reminders_needing_attention(db: Session, user: User) -> list[ReminderView]:
    """Overdue and due-soon reminders of all the user's cars, most urgent first."""
    return [view for view in active_reminders(db, user) if view.state.status in NEEDS_ATTENTION]


def calendar_file(views: list[ReminderView], name: str) -> bytes:
    """Active reminders with a due date as an .ics file (see app/ics.py). A reminder by mileage
    only has no date to put in a calendar, so it is left out."""
    events = [
        CalendarEvent(
            uid=f"garagelog-reminder-{view.reminder.id}",
            day=view.reminder.due_date,
            summary=f"{view.car.name}: {view.reminder.title}",
            description=_calendar_description(view),
        )
        for view in views
        if view.reminder.due_date is not None
    ]
    return calendar(events, name, now=dt.datetime.now(dt.UTC))


def _calendar_description(view: ReminderView) -> str:
    reminder = view.reminder
    due = [f"do {format_date(reminder.due_date)}"]
    if reminder.due_odometer_km is not None:
        due.append(f"do {format_km(reminder.due_odometer_km)} (co nastąpi wcześniej)")
    lines = [f"Termin: {' lub '.join(due)}"]
    if view.repeat_text:
        lines.append(f"Powtarza się {view.repeat_text}.")
    if reminder.notes:
        lines.append(reminder.notes)
    return "\n".join(lines)


def create_reminder(db: Session, car: Car, form: ReminderForm) -> Reminder:
    reminder = Reminder(car_id=car.id, **form.model_dump())
    db.add(reminder)
    db.flush()
    return reminder


def update_reminder(db: Session, reminder: Reminder, form: ReminderForm) -> None:
    for field, value in form.model_dump().items():
        setattr(reminder, field, value)
    db.flush()


def complete_reminder(db: Session, reminder: Reminder, car: Car) -> Reminder | None:
    """Mark as done. A recurring reminder also gets its next occurrence, which is returned."""
    if reminder.completed_at is not None:
        return None  # already done (e.g. a double click): no second next occurrence
    reminder.completed_at = dt.datetime.now(dt.UTC)
    due = next_due(
        reminder.repeat_months,
        reminder.repeat_km,
        done_on=today(),
        done_at_km=cars_service.current_odometer_km(db, car),
    )
    next_reminder = None
    if due is not None:
        next_reminder = Reminder(
            car_id=car.id,
            title=reminder.title,
            notes=reminder.notes,
            due_date=due[0],
            due_odometer_km=due[1],
            repeat_months=reminder.repeat_months,
            repeat_km=reminder.repeat_km,
            created_from_id=reminder.id,
        )
        db.add(next_reminder)
    db.flush()
    return next_reminder


def reopen_reminder(db: Session, reminder: Reminder) -> None:
    """Undo "done" (e.g. a misclick). The next occurrence created by completing it is removed
    too, unless that one has been completed in the meantime."""
    reminder.completed_at = None
    db.execute(
        delete(Reminder).where(
            Reminder.created_from_id == reminder.id, Reminder.completed_at.is_(None)
        )
    )
    db.flush()


def delete_reminder(db: Session, reminder: Reminder) -> None:
    db.delete(reminder)
    db.flush()
