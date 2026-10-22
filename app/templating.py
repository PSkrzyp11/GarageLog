from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.formatting import (
    format_consumption,
    format_date,
    format_km,
    format_liters,
    format_pln,
    plural,
)
from app.models import Car
from app.security import csrf_input
from app.static_files import static_url
from app.timeutils import local_date

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


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


def is_htmx(request: Request) -> bool:
    """An HTMX request that swaps a part of the page, so a fragment is enough.

    A history-restore request (Back button after an HTMX navigation) needs the full page.
    """
    return (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-History-Restore-Request") != "true"
    )


# Jinja2Templates enables autoescaping for .html files, which protects against XSS.
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.globals["csrf_input"] = csrf_input
templates.env.globals["static_url"] = static_url
templates.env.filters["km"] = format_km
templates.env.filters["pln"] = format_pln
templates.env.filters["pl_date"] = format_date
templates.env.filters["local_date"] = local_date
templates.env.filters["liters"] = format_liters
templates.env.filters["per_100km"] = format_consumption
templates.env.filters["plural"] = plural
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
    # The same URL may return a full page or an HTMX fragment: caches must keep them apart.
    all_headers = {"Vary": "HX-Request", **(headers or {})}
    return templates.TemplateResponse(
        request, name, full_context, status_code=status_code, headers=all_headers
    )
