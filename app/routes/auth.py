from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from app.deps import DbSession, FormData, OptionalUser
from app.schemas import LoginForm, RegisterForm, form_errors, parse_form
from app.security import SESSION_COOKIE, delete_cookie, set_cookie
from app.services import auth as auth_service
from app.templating import render

router = APIRouter()

LOGIN_FAILED_MESSAGE = "Nieprawidłowy e-mail lub hasło."


def _logged_in_redirect(request: Request, session_token: str) -> RedirectResponse:
    # 303 See Other: after a POST the browser follows the redirect with GET (POST-redirect-GET).
    response = RedirectResponse(request.url_for("dashboard"), status.HTTP_303_SEE_OTHER)
    set_cookie(
        response,
        request,
        SESSION_COOKIE,
        session_token,
        max_age=int(auth_service.SESSION_LIFETIME.total_seconds()),
    )
    return response


@router.get("/register")
def register_page(request: Request, user: OptionalUser) -> Response:
    if user is not None:
        return RedirectResponse(request.url_for("dashboard"), status.HTTP_303_SEE_OTHER)
    return render(request, "auth/register.html")


@router.post("/register")
def register(request: Request, db: DbSession, data: FormData) -> Response:
    email = data.get("email", "")
    try:
        form = parse_form(RegisterForm, data)
    except ValidationError as exc:
        return render(
            request,
            "auth/register.html",
            {"errors": form_errors(exc), "email": email},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    try:
        user = auth_service.register_user(db, form.email, form.password)
    except auth_service.EmailAlreadyRegisteredError:
        # Reveals that the e-mail is registered — unavoidable on a sign-up form without
        # e-mail confirmation; the login form, by contrast, never says which part was wrong.
        return render(
            request,
            "auth/register.html",
            {"errors": {"email": "Konto z tym adresem e-mail już istnieje."}, "email": email},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    session_token = auth_service.create_session(db, user)
    db.commit()
    return _logged_in_redirect(request, session_token)


@router.get("/login")
def login_page(request: Request, user: OptionalUser) -> Response:
    if user is not None:
        return RedirectResponse(request.url_for("dashboard"), status.HTTP_303_SEE_OTHER)
    return render(request, "auth/login.html")


@router.post("/login")
def login(request: Request, db: DbSession, data: FormData) -> Response:
    email = data.get("email", "")
    try:
        form = parse_form(LoginForm, data)
    except ValidationError as exc:
        return render(
            request,
            "auth/login.html",
            {"errors": form_errors(exc), "email": email},
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    user = auth_service.authenticate(db, form.email, form.password)
    if user is None:
        return render(
            request,
            "auth/login.html",
            {"errors": {"form": LOGIN_FAILED_MESSAGE}, "email": email},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Always a brand-new session token: a token planted before login (session fixation)
    # is never promoted to a logged-in session.
    old_token = request.cookies.get(SESSION_COOKIE)
    if old_token:
        auth_service.delete_session(db, old_token)
    session_token = auth_service.create_session(db, user)
    db.commit()
    return _logged_in_redirect(request, session_token)


@router.post("/logout")
def logout(request: Request, db: DbSession) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        # Deleting the row is what really logs out — the cookie alone would still be valid.
        auth_service.delete_session(db, token)
        db.commit()

    response = RedirectResponse(request.url_for("login_page"), status.HTTP_303_SEE_OTHER)
    delete_cookie(response, request, SESSION_COOKIE)
    return response
