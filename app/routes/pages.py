import datetime as dt

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import CurrentUser, DbSession
from app.services import cars as cars_service
from app.services import costs as costs_service
from app.services import reminders as reminders_service
from app.static_files import static_url
from app.templating import render
from app.timeutils import today

router = APIRouter()


@router.get("/")
def dashboard(request: Request, user: CurrentUser, db: DbSession) -> HTMLResponse:
    current_year = today().year
    return render(
        request,
        "dashboard.html",
        {
            "user": user,
            "cars": cars_service.list_cars(db, user),
            "year": current_year,
            "year_costs": costs_service.costs_since(db, user, dt.date(current_year, 1, 1)),
            "urgent_reminders": reminders_service.reminders_needing_attention(db, user),
        },
    )


@router.get("/favicon.ico", include_in_schema=False)
def favicon(request: Request) -> RedirectResponse:
    """Browsers ask for /favicon.ico on their own; point them at the SVG icon."""
    return RedirectResponse(static_url(request, "favicon.svg"), status.HTTP_301_MOVED_PERMANENTLY)


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker and CI; does not touch the database."""
    return {"status": "ok"}
