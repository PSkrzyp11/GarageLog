"""Passwords, session tokens, CSRF protection and security headers.

FastAPI has no built-in user sessions or CSRF protection, so they live here, in one place.
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Awaitable, Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request, Response, status
from markupsafe import Markup
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.csv_import import MAX_CSV_BYTES
from app.receipts import MAX_RECEIPT_BYTES

SESSION_COOKIE = "session"
CSRF_COOKIE = "csrftoken"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

SECURITY_HEADERS = {
    # Only resources from our own origin; no inline scripts, no embedding in frames.
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'self'; form-action 'self'; "
        "frame-ancestors 'none'; object-src 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
    # The app needs none of these browser features; a script injected despite the CSP
    # could not ask for them either.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
}

# One year; without includeSubDomains, so other services on the same domain are not affected.
HSTS_HEADER = "max-age=31536000"

# The largest form (a 2 000-character note in Polish, URL-encoded) is about 20 KB.
MAX_REQUEST_BODY_BYTES = 64 * 1024
# Only the forms that carry a file get a larger limit: the refuel and service forms (a receipt
# or an invoice) and the CSV import.
UPLOAD_LIMITS = [
    (
        re.compile(r"/cars/\d+/(fuel|service)/(new|\d+/edit)"),
        MAX_RECEIPT_BYTES + MAX_REQUEST_BODY_BYTES,
    ),
    (re.compile(r"/cars/\d+/import"), 2 * MAX_CSV_BYTES + MAX_REQUEST_BODY_BYTES),  # two files
]

# --- Passwords --------------------------------------------------------------------------

# Argon2id with the library's default parameters (the RFC 9106 recommendation).
_password_hasher = PasswordHasher()
# Checked against when the e-mail is unknown, so a failed login takes about the same time
# whether or not the account exists (otherwise timing would reveal registered e-mails).
_DUMMY_PASSWORD_HASH = _password_hasher.hash("dummy-password-used-only-for-timing")


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with weaker parameters than the current ones."""
    return _password_hasher.check_needs_rehash(password_hash)


def spend_password_check_time(password: str) -> None:
    verify_password(_DUMMY_PASSWORD_HASH, password)


# --- Session tokens ---------------------------------------------------------------------


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Only this hash is stored, so a leaked database does not contain usable sessions."""
    return hashlib.sha256(token.encode()).hexdigest()


def set_cookie(
    response: Response, request: Request, name: str, value: str, max_age: int | None = None
) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        httponly=True,  # not readable from JavaScript
        samesite="lax",  # not sent with cross-site POST requests
        secure=_cookies_require_https(request),
    )


def delete_cookie(response: Response, request: Request, name: str) -> None:
    response.delete_cookie(
        name, path="/", httponly=True, samesite="lax", secure=_cookies_require_https(request)
    )


def _cookies_require_https(request: Request) -> bool:
    return request.app.state.settings.app_env == "production"


# --- CSRF -------------------------------------------------------------------------------
#
# "Signed double-submit cookie": the token is stored in a cookie and also sent in every form
# (or the X-CSRF-Token header). Another site can make the browser send our cookie, but cannot
# read it, so it cannot put the same value in the form. The token is signed with SECRET_KEY
# and bound to the current session cookie, so a token from another session is rejected and
# a new one is issued automatically after logging in or out.


def _csrf_signature(secret_key: str, nonce: str, session_token: str | None) -> str:
    message = f"{session_token or ''}:{nonce}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


def create_csrf_token(secret_key: str, session_token: str | None) -> str:
    nonce = secrets.token_urlsafe(16)
    return f"{nonce}.{_csrf_signature(secret_key, nonce, session_token)}"


def is_csrf_token_valid(token: str, secret_key: str, session_token: str | None) -> bool:
    nonce, _, signature = token.partition(".")
    if not nonce or not signature:
        return False
    expected = _csrf_signature(secret_key, nonce, session_token)
    return hmac.compare_digest(signature.encode(), expected.encode())


def get_csrf_token(request: Request) -> str:
    """Token for the forms on the page being rendered.

    Reuses the cookie when it is still valid for the current session; otherwise creates a new
    token, which `security_middleware` then stores in the cookie.
    """
    new_token = getattr(request.state, "new_csrf_token", None)
    if new_token:
        return new_token

    secret_key = request.app.state.settings.secret_key
    session_token = request.cookies.get(SESSION_COOKIE)
    cookie_token = request.cookies.get(CSRF_COOKIE)
    if cookie_token and is_csrf_token_valid(cookie_token, secret_key, session_token):
        return cookie_token

    request.state.new_csrf_token = create_csrf_token(secret_key, session_token)
    return request.state.new_csrf_token


def csrf_input(request: Request) -> Markup:
    """Hidden form field for templates: {{ csrf_input(request) }}."""
    return Markup('<input type="hidden" name="{}" value="{}">').format(
        CSRF_FORM_FIELD, get_csrf_token(request)
    )


async def verify_csrf(request: Request) -> None:
    """App-wide dependency: every state-changing request must carry a valid CSRF token."""
    if request.method in SAFE_METHODS:
        return

    submitted = request.headers.get(CSRF_HEADER)
    if submitted is None:
        # FastAPI caches the parsed form on the request, so the endpoint can still read it.
        submitted = (await request.form()).get(CSRF_FORM_FIELD)

    cookie_token = request.cookies.get(CSRF_COOKIE)
    valid = (
        isinstance(submitted, str)
        and cookie_token is not None
        and hmac.compare_digest(submitted.encode(), cookie_token.encode())
        and is_csrf_token_valid(
            cookie_token,
            request.app.state.settings.secret_key,
            request.cookies.get(SESSION_COOKIE),
        )
    )
    if not valid:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Formularz wygasł lub jest nieprawidłowy. Odśwież stronę i spróbuj ponownie.",
        )


# --- Middleware -------------------------------------------------------------------------


async def security_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)

    new_csrf_token = getattr(request.state, "new_csrf_token", None)
    if new_csrf_token:
        set_cookie(response, request, CSRF_COOKIE, new_csrf_token)

    response.headers.update(SECURITY_HEADERS)
    if request.app.state.settings.app_env == "production":
        # Production runs only behind HTTPS: browsers must never fall back to plain HTTP.
        response.headers["Strict-Transport-Security"] = HSTS_HEADER
    return response


class RequestBodyLimitMiddleware:
    """Stops reading a request body after MAX_REQUEST_BODY_BYTES and answers 413.

    Every POST form is parsed before the user is known (the CSRF check reads it), and neither
    uvicorn nor Starlette limits the size of a URL-encoded body. Counting the bytes actually
    received, instead of trusting Content-Length, also covers chunked requests.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        received = 0
        limit = next(
            (limit for path, limit in UPLOAD_LIMITS if path.fullmatch(scope["path"])),
            MAX_REQUEST_BODY_BYTES,
        )

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Raised while a route reads the form, so the usual error page is shown.
                    raise HTTPException(
                        status.HTTP_413_CONTENT_TOO_LARGE, "Przesłane dane są za duże."
                    )
            return message

        await self.app(scope, limited_receive, send)
