"""Reminders of one car (/cars/{car_id}/reminders/...)."""

from collections.abc import Mapping

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.deps import CurrentUser, DbSession, FormData, OwnedCar, OwnedReminder
from app.models import Car, Reminder, User
from app.schemas import ReminderForm, form_errors, parse_form
from app.services import reminders as reminders_service
from app.templating import render

router = APIRouter(prefix="/cars/{car_id}/reminders")


def _back(request: Request, car: Car, data: Mapping[str, str] | None = None) -> RedirectResponse:
    """Where to go after an action. Forms send a page *name*, never a URL, so this can't be
    abused to redirect users to another site (an "open redirect")."""
    if data is not None and data.get("return_to") == "dashboard":
        url = request.url_for("dashboard")
    else:
        url = request.url_for("car_reminders", car_id=car.id)
    return RedirectResponse(url, status.HTTP_303_SEE_OTHER)


def _form(
    request: Request,
    user: User,
    car: Car,
    values: Mapping[str, str],
    reminder: Reminder | None = None,
    errors: Mapping[str, str] | None = None,
) -> Response:
    return render(
        request,
        "reminders/form.html",
        {
            "user": user,
            "car": car,
            "reminder": reminder,
            "values": values,
            "errors": errors or {},
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if errors else status.HTTP_200_OK,
    )


@router.get("")
def car_reminders(request: Request, user: CurrentUser, car: OwnedCar, db: DbSession) -> Response:
    return render(
        request,
        "reminders/list.html",
        {"user": user, "car": car, "reminders": reminders_service.car_reminders(db, car)},
    )


@router.get("/new")
def new_reminder_page(request: Request, user: CurrentUser, car: OwnedCar) -> Response:
    return _form(request, user, car, {})


@router.post("/new")
def create_reminder(
    request: Request, user: CurrentUser, car: OwnedCar, db: DbSession, data: FormData
) -> Response:
    try:
        form = parse_form(ReminderForm, data)
    except ValidationError as exc:
        return _form(request, user, car, data, errors=form_errors(exc))

    reminders_service.create_reminder(db, car, form)
    db.commit()
    return _back(request, car)


@router.get("/{reminder_id}/edit")
def edit_reminder_page(
    request: Request, user: CurrentUser, car: OwnedCar, reminder: OwnedReminder
) -> Response:
    values = {
        "title": reminder.title,
        "due_date": reminder.due_date.isoformat() if reminder.due_date else "",
        "due_odometer_km": (
            "" if reminder.due_odometer_km is None else str(reminder.due_odometer_km)
        ),
        "notes": reminder.notes or "",
    }
    return _form(request, user, car, values, reminder=reminder)


@router.post("/{reminder_id}/edit")
def update_reminder(
    request: Request,
    user: CurrentUser,
    car: OwnedCar,
    reminder: OwnedReminder,
    db: DbSession,
    data: FormData,
) -> Response:
    try:
        form = parse_form(ReminderForm, data)
    except ValidationError as exc:
        return _form(request, user, car, data, reminder=reminder, errors=form_errors(exc))

    reminders_service.update_reminder(db, reminder, form)
    db.commit()
    return _back(request, car)


@router.post("/{reminder_id}/complete")
def complete_reminder(
    request: Request, car: OwnedCar, reminder: OwnedReminder, db: DbSession, data: FormData
) -> Response:
    reminders_service.set_completed(db, reminder, completed=True)
    db.commit()
    return _back(request, car, data)


@router.post("/{reminder_id}/reopen")
def reopen_reminder(
    request: Request, car: OwnedCar, reminder: OwnedReminder, db: DbSession, data: FormData
) -> Response:
    reminders_service.set_completed(db, reminder, completed=False)
    db.commit()
    return _back(request, car, data)


@router.get("/{reminder_id}/delete")
def delete_reminder_page(
    request: Request, user: CurrentUser, car: OwnedCar, reminder: OwnedReminder
) -> Response:
    return render(
        request,
        "entries/delete.html",
        {
            "user": user,
            "car": car,
            "question": f"Usunąć przypomnienie „{reminder.title}”?",
            "details": "Jeśli zostało zrobione, możesz zamiast tego oznaczyć je jako wykonane.",
            "action_url": str(
                request.url_for("delete_reminder", car_id=car.id, reminder_id=reminder.id)
            ),
        },
    )


@router.post("/{reminder_id}/delete")
def delete_reminder(
    request: Request, car: OwnedCar, reminder: OwnedReminder, db: DbSession
) -> Response:
    reminders_service.delete_reminder(db, reminder)
    db.commit()
    return _back(request, car)
