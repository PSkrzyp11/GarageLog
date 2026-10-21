from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.deps import CurrentUser
from app.templating import render

router = APIRouter()


@router.get("/")
def dashboard(request: Request, user: CurrentUser) -> HTMLResponse:
    return render(request, "dashboard.html", {"user": user})


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker and CI; does not touch the database."""
    return {"status": "ok"}
