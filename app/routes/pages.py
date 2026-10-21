from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.deps import CurrentUser, DbSession
from app.services import cars as cars_service
from app.templating import render

router = APIRouter()


@router.get("/")
def dashboard(request: Request, user: CurrentUser, db: DbSession) -> HTMLResponse:
    cars = cars_service.list_cars(db, user)
    return render(request, "dashboard.html", {"user": user, "cars": cars})


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker and CI; does not touch the database."""
    return {"status": "ok"}
