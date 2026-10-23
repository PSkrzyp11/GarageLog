"""Service entries, refuels and odometer readings of one car (/cars/{car_id}/...)."""

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.deps import (
    ActiveCar,
    CurrentUser,
    DbSession,
    FormData,
    OwnedFuelEntry,
    OwnedReading,
    OwnedServiceEntry,
    ReceiptUpload,
)
from app.formatting import (
    decimal_for_input,
    format_date,
    format_km,
    format_liters,
    format_pln,
)
from app.models import Car, FuelEntry, OdometerReading, ServiceCategory, ServiceEntry, User
from app.receipts import JPEG, ReceiptError, prepare_receipt
from app.schemas import (
    FuelEntryForm,
    OdometerReadingForm,
    ServiceEntryForm,
    form_errors,
    parse_form,
)
from app.services import cars as cars_service
from app.services import entries as entries_service
from app.services.entries import EntryValidationError
from app.templating import is_htmx, render
from app.timeutils import today

router = APIRouter(prefix="/cars/{car_id}")

CATEGORY_OPTIONS = [(category.value, category.label) for category in ServiceCategory]


def _back_to_car(request: Request, car: Car) -> RedirectResponse:
    return RedirectResponse(request.url_for("car_detail", car_id=car.id), status.HTTP_303_SEE_OTHER)


def _after_delete(request: Request, car: Car, db: DbSession) -> Response:
    """Without JavaScript: back to the car page. With HTMX the response replaces the deleted
    row, so its empty main content removes the row; the current mileage in the page header is
    sent "out of band" (hx-swap-oob), because deleting an entry may lower it."""
    if not is_htmx(request):
        return _back_to_car(request, car)
    return render(
        request,
        "cars/_odometer.html",
        {"odometer_km": cars_service.current_odometer_km(db, car), "oob": True},
    )


def _form_page(
    request: Request,
    template: str,
    user: User,
    car: Car,
    values: Mapping[str, str],
    entry: ServiceEntry | FuelEntry | OdometerReading | None,
    errors: Mapping[str, str] | None,
    extra: Mapping[str, Any] | None = None,
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
            "today": today().isoformat(),
            **(extra or {}),
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


def _errors(
    exc: ValidationError | EntryValidationError | ReceiptError, upload: bytes | None = None
) -> dict[str, str]:
    """Form errors from the form validation, a rule checked in the service or the receipt."""
    if isinstance(exc, ReceiptError):
        return {"receipt": str(exc)}
    errors = form_errors(exc) if isinstance(exc, ValidationError) else {exc.field: str(exc)}
    if upload is not None:
        # Browsers never fill a file field in again: say so, or the receipt is silently lost.
        errors["receipt"] = "Popraw błędy i wybierz plik paragonu jeszcze raz."
    return errors


# --- Service entries --------------------------------------------------------------------


def _service_form(
    request: Request,
    user: User,
    car: Car,
    values: Mapping[str, str],
    entry: ServiceEntry | None = None,
    errors: Mapping[str, str] | None = None,
) -> Response:
    extra = {"category_options": CATEGORY_OPTIONS}
    return _form_page(request, "entries/service_form.html", user, car, values, entry, errors, extra)


@router.get("/service/new")
def new_service_entry_page(request: Request, user: CurrentUser, car: ActiveCar) -> Response:
    defaults = {"date": today().isoformat(), "category": ServiceCategory.MAINTENANCE.value}
    return _service_form(request, user, car, defaults)


@router.post("/service/new")
def create_service_entry(
    request: Request, user: CurrentUser, car: ActiveCar, db: DbSession, data: FormData
) -> Response:
    try:
        form = parse_form(ServiceEntryForm, data)
        entries_service.create_service_entry(db, car, form)
    except (ValidationError, EntryValidationError) as exc:
        return _service_form(request, user, car, data, errors=_errors(exc))

    db.commit()
    return _back_to_car(request, car)


@router.get("/service/{entry_id}/edit")
def edit_service_entry_page(
    request: Request, user: CurrentUser, car: ActiveCar, entry: OwnedServiceEntry
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
    car: ActiveCar,
    entry: OwnedServiceEntry,
    db: DbSession,
    data: FormData,
) -> Response:
    try:
        form = parse_form(ServiceEntryForm, data)
        entries_service.update_service_entry(db, entry, car, form)
    except (ValidationError, EntryValidationError) as exc:
        return _service_form(request, user, car, data, entry=entry, errors=_errors(exc))

    db.commit()
    return _back_to_car(request, car)


@router.get("/service/{entry_id}/delete")
def delete_service_entry_page(
    request: Request, user: CurrentUser, car: ActiveCar, entry: OwnedServiceEntry
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
    request: Request, car: ActiveCar, entry: OwnedServiceEntry, db: DbSession
) -> Response:
    entries_service.delete_entry(db, entry)
    db.commit()
    return _after_delete(request, car, db)


# --- Refuels ----------------------------------------------------------------------------


def _fuel_form(
    request: Request,
    user: User,
    car: Car,
    values: Mapping[str, str],
    entry: FuelEntry | None = None,
    errors: Mapping[str, str] | None = None,
    last_odometer_km: int | None = None,
    receipt_type: str | None = None,
) -> Response:
    fuels = entries_service.allowed_fuel_types(car, entry)
    extra = {
        "fuel_options": [(fuel.value, fuel.label) for fuel in fuels],
        # A new refuel: shown as a hint, so the mileage is easy to check at the pump.
        "last_odometer_km": last_odometer_km,
        # An edited refuel: its current receipt, if any (JPEG photo or PDF).
        "receipt_type": receipt_type,
        "jpeg": JPEG,
    }
    return _form_page(request, "entries/fuel_form.html", user, car, values, entry, errors, extra)


@router.get("/fuel/new")
def new_fuel_entry_page(
    request: Request, user: CurrentUser, car: ActiveCar, db: DbSession
) -> Response:
    # Made to be filled in quickly at the pump on a phone: only mileage, litres and amount
    # usually need typing.
    defaults = {
        "date": today().isoformat(),
        "fuel_type": entries_service.usual_fuel_type(db, car).value,
        "is_full_tank": "on",  # most refuels are to a full tank
    }
    return _fuel_form(
        request, user, car, defaults, last_odometer_km=cars_service.current_odometer_km(db, car)
    )


@router.post("/fuel/new")
def create_fuel_entry(
    request: Request,
    user: CurrentUser,
    car: ActiveCar,
    db: DbSession,
    data: FormData,
    upload: ReceiptUpload,
) -> Response:
    try:
        form = parse_form(FuelEntryForm, data)
        receipt = prepare_receipt(upload) if upload is not None else None
        entry = entries_service.create_fuel_entry(db, car, form)
    except (ValidationError, EntryValidationError, ReceiptError) as exc:
        last_km = cars_service.current_odometer_km(db, car)
        errors = _errors(exc, upload)
        return _fuel_form(request, user, car, data, errors=errors, last_odometer_km=last_km)

    if receipt is not None:
        entries_service.save_receipt(db, entry, receipt)
    db.commit()
    return _back_to_car(request, car)


@router.get("/fuel/{fuel_id}/edit")
def edit_fuel_entry_page(
    request: Request, user: CurrentUser, car: ActiveCar, entry: OwnedFuelEntry, db: DbSession
) -> Response:
    values = {
        "date": entry.date.isoformat(),
        "odometer_km": str(entry.odometer_km),
        "fuel_type": entry.fuel_type.value,
        "liters": decimal_for_input(entry.liters),
        "total_cost_pln": decimal_for_input(entry.total_cost_pln),
        "is_full_tank": "on" if entry.is_full_tank else "",
        "missed_previous": "on" if entry.missed_previous else "",
    }
    receipt_type = entries_service.receipt_content_type(db, entry)
    return _fuel_form(request, user, car, values, entry=entry, receipt_type=receipt_type)


@router.post("/fuel/{fuel_id}/edit")
def update_fuel_entry(
    request: Request,
    user: CurrentUser,
    car: ActiveCar,
    entry: OwnedFuelEntry,
    db: DbSession,
    data: FormData,
    upload: ReceiptUpload,
) -> Response:
    try:
        form = parse_form(FuelEntryForm, data)
        receipt = prepare_receipt(upload) if upload is not None else None
        entries_service.update_fuel_entry(db, entry, car, form)
    except (ValidationError, EntryValidationError, ReceiptError) as exc:
        receipt_type = entries_service.receipt_content_type(db, entry)
        errors = _errors(exc, upload)
        return _fuel_form(
            request, user, car, data, entry=entry, errors=errors, receipt_type=receipt_type
        )

    if receipt is not None:
        entries_service.save_receipt(db, entry, receipt)
    elif data.get("remove_receipt") == "on":
        entries_service.remove_receipt(db, entry)
    db.commit()
    return _back_to_car(request, car)


@router.get("/fuel/{fuel_id}/receipt")
def fuel_receipt(entry: OwnedFuelEntry, db: DbSession) -> Response:
    receipt = entries_service.get_receipt(db, entry)
    if receipt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    # A photo (re-encoded by us) opens in the browser. A PDF is only offered as a download, so
    # whatever it contains is never shown as a page of this site.
    is_photo = receipt.content_type == JPEG
    disposition = "inline" if is_photo else "attachment"
    filename = f"paragon-{entry.date.isoformat()}.{'jpg' if is_photo else 'pdf'}"
    return Response(
        receipt.data,
        media_type=receipt.content_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, no-store",  # personal data, like the CSV export
        },
    )


@router.get("/fuel/{fuel_id}/delete")
def delete_fuel_entry_page(
    request: Request, user: CurrentUser, car: ActiveCar, entry: OwnedFuelEntry
) -> Response:
    details = (
        format_date(entry.date),
        entry.fuel_type.label,
        format_liters(entry.liters),
        format_pln(entry.total_cost_pln),
    )
    return _delete_page(
        request,
        user,
        car,
        question="Usunąć tankowanie?",
        details=" · ".join(details),
        action_url=str(request.url_for("delete_fuel_entry", car_id=car.id, fuel_id=entry.id)),
    )


@router.post("/fuel/{fuel_id}/delete")
def delete_fuel_entry(
    request: Request, car: ActiveCar, entry: OwnedFuelEntry, db: DbSession
) -> Response:
    entries_service.delete_entry(db, entry)
    db.commit()
    return _after_delete(request, car, db)


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
def new_reading_page(request: Request, user: CurrentUser, car: ActiveCar) -> Response:
    return _reading_form(request, user, car, {"date": today().isoformat()})


@router.post("/odometer/new")
def create_reading(
    request: Request, user: CurrentUser, car: ActiveCar, db: DbSession, data: FormData
) -> Response:
    try:
        form = parse_form(OdometerReadingForm, data)
        entries_service.create_reading(db, car, form)
    except (ValidationError, EntryValidationError) as exc:
        return _reading_form(request, user, car, data, errors=_errors(exc))

    db.commit()
    return _back_to_car(request, car)


@router.get("/odometer/{reading_id}/edit")
def edit_reading_page(
    request: Request, user: CurrentUser, car: ActiveCar, reading: OwnedReading
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
    car: ActiveCar,
    reading: OwnedReading,
    db: DbSession,
    data: FormData,
) -> Response:
    try:
        form = parse_form(OdometerReadingForm, data)
        entries_service.update_reading(db, reading, car, form)
    except (ValidationError, EntryValidationError) as exc:
        return _reading_form(request, user, car, data, reading=reading, errors=_errors(exc))

    db.commit()
    return _back_to_car(request, car)


@router.get("/odometer/{reading_id}/delete")
def delete_reading_page(
    request: Request, user: CurrentUser, car: ActiveCar, reading: OwnedReading
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
    request: Request, car: ActiveCar, reading: OwnedReading, db: DbSession
) -> Response:
    entries_service.delete_entry(db, reading)
    db.commit()
    return _after_delete(request, car, db)
