"""The user's own account (/account/...): password change, logged-in devices, the secret
calendar link, a copy of all the data and deleting the account."""

from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.deps import MAX_ID, CurrentUser, DbSession, FormData
from app.models import User
from app.schemas import PasswordChangeForm, form_errors, parse_form
from app.security import SESSION_COOKIE, delete_cookie
from app.services import account_data
from app.services import auth as auth_service
from app.templating import render
from app.timeutils import today

router = APIRouter(prefix="/account")

# ?done=... after a redirect. Only these fixed messages can be shown, never text from the URL.
DONE_MESSAGES = {
    "password": "Hasło zostało zmienione. Inne urządzenia zostały wylogowane.",
    "sessions": "Wylogowano wszystkie inne urządzenia.",
    "session": "Wylogowano wybrane urządzenie.",
    "calendar_off": "Link do kalendarza został wyłączony.",
}


def _account_page(
    request: Request,
    user: User,
    db: DbSession,
    errors: Mapping[str, str] | None = None,
    done: str = "",
    calendar_token: str | None = None,
) -> Response:
    calendar_url = None
    if calendar_token is not None:
        calendar_url = str(request.url_for("subscribed_calendar", token=calendar_token))
    return render(
        request,
        "account.html",
        {
            "user": user,
            "sessions": auth_service.list_sessions(db, user, request.cookies[SESSION_COOKIE]),
            "done_message": DONE_MESSAGES.get(done),
            "errors": errors or {},
            # Only right after creating it: the link itself is not stored, just its hash.
            "calendar_url": calendar_url,
            # webcal:// opens the "subscribe to calendar" dialog of Apple Calendar and Outlook.
            "webcal_url": calendar_url and "webcal" + calendar_url[calendar_url.index(":") :],
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


@router.post("/sessions/{session_id}/logout")
def logout_session(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    session_id: Annotated[int, Path(ge=1, le=MAX_ID)],
) -> Response:
    """One other device. Someone else's session, or the current one, is "not found"."""
    if not auth_service.delete_other_session(db, user, session_id, request.cookies[SESSION_COOKIE]):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    db.commit()
    return _done(request, "session")


@router.post("/calendar")
def create_calendar_link(request: Request, user: CurrentUser, db: DbSession) -> Response:
    """A new secret link; any previous one stops working. Shown on this response only (not
    after a redirect), because it cannot be read back from the database."""
    token = auth_service.create_calendar_token(db, user)
    db.commit()
    return _account_page(request, user, db, calendar_token=token)


@router.post("/calendar/revoke")
def revoke_calendar_link(request: Request, user: CurrentUser, db: DbSession) -> Response:
    auth_service.revoke_calendar_token(db, user)
    db.commit()
    return _done(request, "calendar_off")


# --- All data / deleting the account ----------------------------------------------------


@router.get("/export.zip")
def export_account(user: CurrentUser, db: DbSession) -> Response:
    """Everything the account holds, in one ZIP (see app/services/account_data.py)."""
    name = f"garagelog-dane-{today().isoformat()}.zip"
    return Response(
        account_data.account_zip(db, user),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",  # personal data, like the CSV export
        },
    )


def _delete_page(request: Request, user: User, error: str | None = None) -> Response:
    return render(
        request,
        "account_delete.html",
        {"user": user, "errors": {"password": error} if error else {}},
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if error else status.HTTP_200_OK,
    )


@router.get("/delete")
def delete_account_page(request: Request, user: CurrentUser) -> Response:
    return _delete_page(request, user)


@router.post("/delete")
def delete_account(request: Request, user: CurrentUser, db: DbSession, data: FormData) -> Response:
    try:
        account_data.delete_account(db, user, data.get("password", ""))
    except auth_service.WrongPasswordError:
        return _delete_page(request, user, "Nieprawidłowe hasło. Konto nie zostało usunięte.")
    db.commit()
    response = RedirectResponse(
        request.url_for("login_page").include_query_params(deleted="1"), status.HTTP_303_SEE_OTHER
    )
    delete_cookie(response, request, SESSION_COOKIE)
    return response
