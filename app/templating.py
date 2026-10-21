from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.models import Car
from app.security import csrf_input

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Jinja2Templates enables autoescaping for .html files, which protects against XSS.
NBSP = " "


def format_km(value: int) -> str:
    """120000 → '120 000 km' (Polish thousands separator; non-breaking spaces)."""
    return f"{value:,}".replace(",", NBSP) + f"{NBSP}km"


def car_summary(car: Car) -> str:
    """'Volkswagen Golf, 2015 · Benzyna + LPG · WA 12345' — optional parts are skipped."""
    parts = []
    make_model = " ".join(part for part in (car.make, car.model) if part)
    year = str(car.production_year) if car.production_year else ""
    if make_model or year:
        parts.append(", ".join(part for part in (make_model, year) if part))
    parts.append(car.primary_fuel.label + (" + LPG" if car.has_lpg else ""))
    if car.registration_number:
        parts.append(car.registration_number)
    return " · ".join(parts)


templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["csrf_input"] = csrf_input
templates.env.filters["km"] = format_km
templates.env.filters["car_summary"] = car_summary


def render(
    request: Request,
    name: str,
    context: Mapping[str, Any] | None = None,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
) -> HTMLResponse:
    # Defaults every template may rely on; the caller's context overrides them.
    full_context = {"user": None, "errors": {}, **(context or {})}
    return templates.TemplateResponse(
        request, name, full_context, status_code=status_code, headers=headers
    )
