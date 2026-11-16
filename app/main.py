from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.db import create_db_engine, create_session_factory
from app.deps import LoginRequired
from app.routes import account, auth, cars, entries, export, importing, pages, reminders
from app.security import (
    RequestBodyLimitMiddleware,
    hide_calendar_tokens_in_access_log,
    security_headers,
    security_middleware,
    verify_csrf,
)
from app.static_files import STATIC_DIR, VersionedStaticFiles
from app.templating import render

ERROR_MESSAGES = {
    404: "Nie znaleziono strony.",
    405: "Ta operacja nie jest dozwolona.",
}
SERVER_ERROR_MESSAGE = "Coś poszło nie tak po stronie serwera."
SERVER_ERROR_HINT = (
    "To nie Twoja wina. Jeśli wysyłany formularz się nie zapisał, spróbuj ponownie za chwilę."
)


async def redirect_to_login(request: Request, exc: Exception) -> Response:
    return RedirectResponse(request.url_for("login_page"), status.HTTP_303_SEE_OTHER)


async def render_http_error(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    message = ERROR_MESSAGES.get(exc.status_code, exc.detail)
    return render(
        request,
        "error.html",
        {"status_code": exc.status_code, "message": message},
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def render_server_error(request: Request, exc: Exception) -> Response:
    """A bug or a database outage: a Polish page instead of Starlette's bare "Internal Server
    Error". Starlette still re-raises the exception, so the traceback lands in the server log;
    the page shows nothing of it. The database may be what failed, so the page reads nothing
    from it (no user in the header)."""
    headers = {**security_headers(request), "Cache-Control": "no-store"}
    try:
        return render(
            request,
            "error.html",
            {"status_code": 500, "message": SERVER_ERROR_MESSAGE, "hint": SERVER_ERROR_HINT},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers=headers,
        )
    except Exception:  # the page itself failed (e.g. a broken template): plain text then
        return PlainTextResponse(
            SERVER_ERROR_MESSAGE, status.HTTP_500_INTERNAL_SERVER_ERROR, headers=headers
        )


async def render_not_found(request: Request, exc: Exception) -> Response:
    # Forms are validated inside the routes, so FastAPI's own validation only fails for
    # malformed URL parameters, e.g. /cars/abc or an out-of-range ID: that page does not exist.
    return await render_http_error(request, StarletteHTTPException(status.HTTP_404_NOT_FOUND))


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Tests pass their own settings; uvicorn uses the environment."""
    settings = settings or get_settings()
    engine = create_db_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        title="GarageLog",
        # Server-rendered HTML app: the auto-generated OpenAPI docs are not needed.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
        # Applied to every route, so a new form cannot be added without CSRF protection.
        dependencies=[Depends(verify_csrf)],
    )
    app.state.settings = settings
    hide_calendar_tokens_in_access_log()
    app.state.session_factory = create_session_factory(engine)

    # Added first, so it sits *inside* security_middleware (the last one added runs first).
    # Its 413 must be raised next to the route, where the error handlers below catch it.
    app.add_middleware(RequestBodyLimitMiddleware)
    app.middleware("http")(security_middleware)
    app.add_exception_handler(LoginRequired, redirect_to_login)
    app.add_exception_handler(StarletteHTTPException, render_http_error)
    app.add_exception_handler(RequestValidationError, render_not_found)
    # Starlette gives this one to its outermost middleware (ServerErrorMiddleware).
    app.add_exception_handler(Exception, render_server_error)

    app.mount("/static", VersionedStaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(cars.router)
    app.include_router(entries.router)
    app.include_router(reminders.router)
    app.include_router(reminders.calendar_router)
    app.include_router(export.router)
    app.include_router(importing.router)

    return app
