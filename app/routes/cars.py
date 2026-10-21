from collections.abc import Mapping

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.deps import CurrentUser, DbSession, FormData, OwnedCar
from app.models import Car, PrimaryFuel, User
from app.schemas import CarCreateForm, CarForm, form_errors, parse_form
from app.services import cars as cars_service
from app.services import entries as entries_service
from app.services.entries import EntryKind
from app.templating import render

router = APIRouter(prefix="/cars")

NAME_TAKEN_MESSAGE = "Masz już auto o tej nazwie."
FUEL_OPTIONS = [(fuel.value, fuel.label) for fuel in PrimaryFuel]


def _car_form(
    request: Request,
    user: User,
    values: Mapping[str, str],
    car: Car | None = None,
    errors: Mapping[str, str] | None = None,
) -> Response:
    """The add/edit form; `car` is None when adding a new one."""
    return render(
        request,
        "cars/form.html",
        {
            "user": user,
            "car": car,
            "values": values,
            "errors": errors or {},
            "fuel_options": FUEL_OPTIONS,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if errors else status.HTTP_200_OK,
    )


def _redirect_to_car(request: Request, car: Car) -> RedirectResponse:
    return RedirectResponse(request.url_for("car_detail", car_id=car.id), status.HTTP_303_SEE_OTHER)


# /cars/new is declared before /cars/{car_id}, so "new" is never taken for a car ID.
@router.get("/new")
def new_car_page(request: Request, user: CurrentUser) -> Response:
    return _car_form(request, user, {"primary_fuel": PrimaryFuel.PETROL.value})


@router.post("/new")
def create_car(request: Request, user: CurrentUser, db: DbSession, data: FormData) -> Response:
    try:
        form = parse_form(CarCreateForm, data)
    except ValidationError as exc:
        return _car_form(request, user, data, errors=form_errors(exc))

    try:
        car = cars_service.create_car(db, user, form)
    except cars_service.CarNameTakenError:
        return _car_form(request, user, data, errors={"name": NAME_TAKEN_MESSAGE})

    db.commit()
    return _redirect_to_car(request, car)


@router.get("/{car_id}")
def car_detail(
    request: Request,
    user: CurrentUser,
    car: OwnedCar,
    db: DbSession,
    kind: str = "",
    year: str = "",
) -> Response:
    """The car with its timeline. ?kind=service|odometer and ?year=2025 filter the list;
    unknown values are ignored (the filter just shows everything)."""
    timeline = entries_service.car_timeline(db, car)
    years = sorted({item.date.year for item in timeline}, reverse=True)
    selected_kind = next((option for option in EntryKind if option.value == kind), None)
    selected_year = int(year) if year.isdigit() and int(year) in years else None

    return render(
        request,
        "cars/detail.html",
        {
            "user": user,
            "car": car,
            "odometer_km": cars_service.current_odometer_km(db, car),
            "timeline": entries_service.filter_timeline(timeline, selected_kind, selected_year),
            "has_entries": bool(timeline),
            "kinds": list(EntryKind),
            "years": years,
            "selected_kind": selected_kind,
            "selected_year": selected_year,
        },
    )


@router.get("/{car_id}/edit")
def edit_car_page(request: Request, user: CurrentUser, car: OwnedCar) -> Response:
    values = {
        "name": car.name,
        "make": car.make or "",
        "model": car.model or "",
        "production_year": str(car.production_year or ""),
        "registration_number": car.registration_number or "",
        "primary_fuel": car.primary_fuel.value,
        "has_lpg": "on" if car.has_lpg else "",
    }
    return _car_form(request, user, values, car=car)


@router.post("/{car_id}/edit")
def update_car(
    request: Request, user: CurrentUser, car: OwnedCar, db: DbSession, data: FormData
) -> Response:
    try:
        form = parse_form(CarForm, data)
    except ValidationError as exc:
        return _car_form(request, user, data, car=car, errors=form_errors(exc))

    try:
        cars_service.update_car(db, car, form)
    except cars_service.CarNameTakenError:
        return _car_form(request, user, data, car=car, errors={"name": NAME_TAKEN_MESSAGE})

    db.commit()
    return _redirect_to_car(request, car)


@router.get("/{car_id}/delete")
def delete_car_page(request: Request, user: CurrentUser, car: OwnedCar, db: DbSession) -> Response:
    return render(
        request,
        "cars/delete.html",
        {
            "user": user,
            "car": car,
            "counts": cars_service.count_entries(db, car),
        },
    )


@router.post("/{car_id}/delete")
def delete_car(request: Request, car: OwnedCar, db: DbSession) -> Response:
    cars_service.delete_car(db, car)
    db.commit()
    return RedirectResponse(request.url_for("dashboard"), status.HTTP_303_SEE_OTHER)
