"""The user's own account: password change and logging out other devices (/account/...)."""

from collections.abc import Mapping

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.deps import CurrentUser, DbSession, FormData
from app.models import User
from app.schemas import PasswordChangeForm, form_errors, parse_form
from app.security import SESSION_COOKIE
from app.services import auth as auth_service
from app.templating import render

router = APIRouter(prefix="/account")

# ?done=... after a redirect. Only these fixed messages can be shown, never text from the URL.
DONE_MESSAGES = {
    "password": "Hasło zostało zmienione. Inne urządzenia zostały wylogowane.",
    "sessions": "Wylogowano wszystkie inne urządzenia.",
}


def _account_page(
    request: Request,
    user: User,
    db: DbSession,
    errors: Mapping[str, str] | None = None,
    done: str = "",
) -> Response:
    return render(
        request,
        "account.html",
        {
            "user": user,
            "other_sessions": auth_service.count_other_sessions(
                db, user, request.cookies[SESSION_COOKIE]
            ),
            "done_message": DONE_MESSAGES.get(done),
            "errors": errors or {},
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if errors else status.HTTP_200_OK,
    )


def _done(request: Request, what: str) -> RedirectResponse:
    url = request.url_for("account_page").include_query_params(done=what)
    return RedirectResponse(url, status.HTTP_303_SEE_OTHER)


@router.get("")
def account_page(request: Request, user: CurrentUser, db: DbSession, done: str = "") -> Response:
    return _account_page(request, user, db, done=done)


@router.post("/password")
def change_password(request: Request, user: CurrentUser, db: DbSession, data: FormData) -> Response:
    try:
        form = parse_form(PasswordChangeForm, data)
    except ValidationError as exc:
        return _account_page(request, user, db, errors=form_errors(exc))

    try:
        auth_service.change_password(
            db,
            user,
            form.current_password,
            form.new_password,
            current_token=request.cookies[SESSION_COOKIE],
        )
    except auth_service.WrongPasswordError:
        errors = {"current_password": "Obecne hasło jest nieprawidłowe."}
        return _account_page(request, user, db, errors=errors)

    db.commit()
    return _done(request, "password")


@router.post("/logout-others")
def logout_other_sessions(request: Request, user: CurrentUser, db: DbSession) -> Response:
    auth_service.delete_other_sessions(db, user, request.cookies[SESSION_COOKIE])
    db.commit()
    return _done(request, "sessions")
