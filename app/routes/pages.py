from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker and CI; does not touch the database."""
    return {"status": "ok"}
