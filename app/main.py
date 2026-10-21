from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.routes import pages

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings; uvicorn uses the environment."""
    settings = settings or get_settings()

    # Server-rendered HTML app: the auto-generated OpenAPI docs are not needed.
    app = FastAPI(title="GarageLog", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)

    return app
