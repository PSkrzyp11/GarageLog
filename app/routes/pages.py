import datetime as dt

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.deps import CurrentUser, DbSession
from app.services import cars as cars_service
from app.services import costs as costs_service
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
        },
    )


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker and CI; does not touch the database."""
    return {"status": "ok"}
