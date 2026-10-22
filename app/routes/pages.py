import datetime as dt

from fastapi import APIRouter, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.deps import CurrentUser, DbSession
from app.services import cars as cars_service
from app.services import costs as costs_service
from app.services import reminders as reminders_service
from app.static_files import static_url
from app.templating import render
from app.timeutils import today

router = APIRouter()

THEME_COLOR = "#1f5fae"  # --color-primary in app.css; also <meta name="theme-color">


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


@router.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest(request: Request) -> JSONResponse:
    """Lets a phone add GarageLog to the home screen as an app, without the browser bars.

    There is deliberately no service worker: it would keep copies of pages with personal data
    on the device, and the app needs the server anyway.
    """
    icons = [
        ("icons/icon-192.png", "192x192", "any"),
        ("icons/icon-512.png", "512x512", "any"),
        ("icons/icon-maskable-512.png", "512x512", "maskable"),
    ]
    return JSONResponse(
        {
            "name": "GarageLog",
            "short_name": "GarageLog",
            "description": "Historia serwisowa, tankowania i koszty Twoich aut.",
            "lang": "pl",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f6f7f9",
            "theme_color": THEME_COLOR,
            "icons": [
                {
                    "src": static_url(request, path),
                    "sizes": sizes,
                    "type": "image/png",
                    "purpose": purpose,
                }
                for path, sizes, purpose in icons
            ],
        },
        media_type="application/manifest+json",
    )


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check used by Docker and CI; does not touch the database."""
    return {"status": "ok"}
