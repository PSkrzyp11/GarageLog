"""Service entries and odometer readings of one car (/cars/{car_id}/...)."""

from collections.abc import Mapping

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.deps import (
    CurrentUser,
    DbSession,
    FormData,
    OwnedCar,
    OwnedReading,
    OwnedServiceEntry,
)
from app.formatting import decimal_for_input, format_date, format_km, format_pln
from app.models import Car, OdometerReading, ServiceCategory, ServiceEntry, User
from app.schemas import OdometerReadingForm, ServiceEntryForm, form_errors, parse_form
from app.services import entries as entries_service
from app.services.entries import OdometerConflictError
from app.templating import render
from app.timeutils import today

router = APIRouter(prefix="/cars/{car_id}")

CATEGORY_OPTIONS = [(category.value, category.label) for category in ServiceCategory]


def _back_to_car(request: Request, car: Car) -> RedirectResponse:
    return RedirectResponse(request.url_for("car_detail", car_id=car.id), status.HTTP_303_SEE_OTHER)


def _form_page(
    request: Request,
    template: str,
    user: User,
    car: Car,
    values: Mapping[str, str],
    entry: ServiceEntry | OdometerReading | None,
    errors: Mapping[str, str] | None,
) -> Response:
    return render(
        request,
        template,
        {
            "user": user,
            "car": car,
            "entry": entry,
            "values": values,
            "errors": errors or {},
            "category_options": CATEGORY_OPTIONS,
            "today": today().isoformat(),
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if errors else status.HTTP_200_OK,
    )


def _delete_page(
    request: Request, user: User, car: Car, question: str, details: str, action_url: str
) -> Response:
    return render(
        request,
        "entries/delete.html",
        {
            "user": user,
            "car": car,
            "question": question,
            "details": details,
            "action_url": action_url,
        },
    )


# --- Service entries --------------------------------------------------------------------


def _service_form(
    request: Request,
    user: User,
    car: Car,
    values: Mapping[str, str],
    entry: ServiceEntry | None = None,
    errors: Mapping[str, str] | None = None,
) -> Response:
    return _form_page(request, "entries/service_form.html", user, car, values, entry, errors)


@router.get("/service/new")
def new_service_entry_page(request: Request, user: CurrentUser, car: OwnedCar) -> Response:
    defaults = {"date": today().isoformat(), "category": ServiceCategory.MAINTENANCE.value}
    return _service_form(request, user, car, defaults)


@router.post("/service/new")
def create_service_entry(
    request: Request, user: CurrentUser, car: OwnedCar, db: DbSession, data: FormData
) -> Response:
    try:
        form = parse_form(ServiceEntryForm, data)
        entries_service.create_service_entry(db, car, form)
    except ValidationError as exc:
        return _service_form(request, user, car, data, errors=form_errors(exc))
    except OdometerConflictError as exc:
        return _service_form(request, user, car, data, errors={"odometer_km": str(exc)})

    db.commit()
    return _back_to_car(request, car)


@router.get("/service/{entry_id}/edit")
def edit_service_entry_page(
    request: Request, user: CurrentUser, car: OwnedCar, entry: OwnedServiceEntry
) -> Response:
    values = {
        "date": entry.date.isoformat(),
        "odometer_km": "" if entry.odometer_km is None else str(entry.odometer_km),
        "category": entry.category.value,
        "title": entry.title,
        "notes": entry.notes or "",
        "cost_pln": decimal_for_input(entry.cost_pln),
    }
    return _service_form(request, user, car, values, entry=entry)


@router.post("/service/{entry_id}/edit")
def update_service_entry(
    request: Request,
    user: CurrentUser,
    car: OwnedCar,
    entry: OwnedServiceEntry,
    db: DbSession,
    data: FormData,
) -> Response:
    try:
        form = parse_form(ServiceEntryForm, data)
        entries_service.update_service_entry(db, entry, car, form)
    except ValidationError as exc:
        return _service_form(request, user, car, data, entry=entry, errors=form_errors(exc))
    except OdometerConflictError as exc:
        errors = {"odometer_km": str(exc)}
        return _service_form(request, user, car, data, entry=entry, errors=errors)

    db.commit()
    return _back_to_car(request, car)


@router.get("/service/{entry_id}/delete")
def delete_service_entry_page(
    request: Request, user: CurrentUser, car: OwnedCar, entry: OwnedServiceEntry
) -> Response:
    return _delete_page(
        request,
        user,
        car,
        question=f"Usunąć wpis „{entry.title}”?",
        details=" · ".join(
            (format_date(entry.date), entry.category.label, format_pln(entry.cost_pln))
        ),
        action_url=str(request.url_for("delete_service_entry", car_id=car.id, entry_id=entry.id)),
    )


@router.post("/service/{entry_id}/delete")
def delete_service_entry(
    request: Request, car: OwnedCar, entry: OwnedServiceEntry, db: DbSession
) -> Response:
    entries_service.delete_service_entry(db, entry)
    db.commit()
    return _back_to_car(request, car)


# --- Odometer readings ------------------------------------------------------------------


def _reading_form(
    request: Request,
    user: User,
    car: Car,
    values: Mapping[str, str],
    reading: OdometerReading | None = None,
    errors: Mapping[str, str] | None = None,
) -> Response:
    return _form_page(request, "entries/reading_form.html", user, car, values, reading, errors)


@router.get("/odometer/new")
def new_reading_page(request: Request, user: CurrentUser, car: OwnedCar) -> Response:
    return _reading_form(request, user, car, {"date": today().isoformat()})


@router.post("/odometer/new")
def create_reading(
    request: Request, user: CurrentUser, car: OwnedCar, db: DbSession, data: FormData
) -> Response:
    try:
        form = parse_form(OdometerReadingForm, data)
        entries_service.create_reading(db, car, form)
    except ValidationError as exc:
        return _reading_form(request, user, car, data, errors=form_errors(exc))
    except OdometerConflictError as exc:
        return _reading_form(request, user, car, data, errors={"odometer_km": str(exc)})

    db.commit()
    return _back_to_car(request, car)


@router.get("/odometer/{reading_id}/edit")
def edit_reading_page(
    request: Request, user: CurrentUser, car: OwnedCar, reading: OwnedReading
) -> Response:
    values = {
        "date": reading.date.isoformat(),
        "odometer_km": str(reading.odometer_km),
        "note": reading.note or "",
    }
    return _reading_form(request, user, car, values, reading=reading)


@router.post("/odometer/{reading_id}/edit")
def update_reading(
    request: Request,
    user: CurrentUser,
    car: OwnedCar,
    reading: OwnedReading,
    db: DbSession,
    data: FormData,
) -> Response:
    try:
        form = parse_form(OdometerReadingForm, data)
        entries_service.update_reading(db, reading, car, form)
    except ValidationError as exc:
        return _reading_form(request, user, car, data, reading=reading, errors=form_errors(exc))
    except OdometerConflictError as exc:
        errors = {"odometer_km": str(exc)}
        return _reading_form(request, user, car, data, reading=reading, errors=errors)

    db.commit()
    return _back_to_car(request, car)


@router.get("/odometer/{reading_id}/delete")
def delete_reading_page(
    request: Request, user: CurrentUser, car: OwnedCar, reading: OwnedReading
) -> Response:
    return _delete_page(
        request,
        user,
        car,
        question="Usunąć odczyt licznika?",
        details=f"{format_date(reading.date)} · {format_km(reading.odometer_km)}",
        action_url=str(request.url_for("delete_reading", car_id=car.id, reading_id=reading.id)),
    )


@router.post("/odometer/{reading_id}/delete")
def delete_reading(
    request: Request, car: OwnedCar, reading: OwnedReading, db: DbSession
) -> Response:
    entries_service.delete_reading(db, reading)
    db.commit()
    return _back_to_car(request, car)
