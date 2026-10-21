from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserSession
from app.security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_csrf_token,
    generate_session_token,
    hash_password,
    hash_session_token,
)
from tests.integration.helpers import (
    EMAIL,
    PASSWORD,
    count,
    csrf_token_from,
    is_logged_in,
    login,
    logout,
    register,
    set_cookie,
)

# --- Registration -----------------------------------------------------------------------


def test_register_creates_account_and_logs_in(client: TestClient, db_session: Session) -> None:
    response = register(client)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/")
    assert is_logged_in(client)
    assert EMAIL in client.get("/").text


def test_register_stores_only_hashes_of_password_and_session_token(
    client: TestClient, db_session: Session
) -> None:
    register(client)
    cookie_token = client.cookies[SESSION_COOKIE]

    user = db_session.scalars(select(User)).one()
    session = db_session.scalars(select(UserSession)).one()

    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert session.token_hash == hash_session_token(cookie_token)
    assert session.token_hash != cookie_token


def test_session_cookie_is_httponly_and_samesite_lax(client: TestClient) -> None:
    set_cookie = register(client).headers["set-cookie"]

    assert set_cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_register_rejects_email_registered_in_different_letter_case(
    client: TestClient, db_session: Session
) -> None:
    register(client, email="jan@example.com")
    logout(client)

    response = register(client, email="JAN@Example.com")

    assert response.status_code == 422
    assert "Konto z tym adresem e-mail już istnieje." in response.text
    assert count(db_session, User) == 1


def test_register_validation_error_keeps_email_but_not_password(
    client: TestClient, db_session: Session
) -> None:
    response = client.post(
        "/register",
        data={
            "email": "jan@example.com",
            "password": "sekretne-haslo-1",
            "password_confirm": "sekretne-haslo-2",
            "csrf_token": csrf_token_from(client, "/register"),
        },
    )

    assert response.status_code == 422
    assert "Hasła nie są takie same." in response.text
    assert 'value="jan@example.com"' in response.text
    assert "sekretne-haslo" not in response.text
    assert count(db_session, User) == 0


# --- Login and logout -------------------------------------------------------------------


def test_login_with_correct_password_and_any_email_case(client: TestClient) -> None:
    register(client)
    logout(client)

    response = login(client, email="Jan@Example.COM")

    assert response.status_code == 303
    assert is_logged_in(client)


def test_login_failure_does_not_reveal_whether_account_exists(client: TestClient) -> None:
    register(client)
    logout(client)

    wrong_password = login(client, password="złe hasło")
    unknown_email = login(client, email="nikt@example.com")

    for response in (wrong_password, unknown_email):
        assert response.status_code == 400
        assert "Nieprawidłowy e-mail lub hasło." in response.text
        assert SESSION_COOKIE not in response.cookies
    assert not is_logged_in(client)


def test_login_never_reuses_a_session_token_set_before_login(client: TestClient) -> None:
    register(client)
    logout(client)
    set_cookie(client, SESSION_COOKIE, "token-planted-by-attacker")

    login(client)

    assert client.cookies[SESSION_COOKIE] != "token-planted-by-attacker"
    assert is_logged_in(client)


def test_logout_deletes_session_so_old_cookie_stops_working(
    client: TestClient, db_session: Session
) -> None:
    register(client)
    old_token = client.cookies[SESSION_COOKIE]

    response = logout(client)

    assert response.status_code == 303
    assert response.headers["location"].endswith("/login")
    assert count(db_session, UserSession) == 0

    set_cookie(client, SESSION_COOKIE, old_token)
    assert not is_logged_in(client)


def test_expired_session_is_rejected(client: TestClient, db_session: Session) -> None:
    user = User(email=EMAIL, password_hash=hash_password(PASSWORD))
    db_session.add(user)
    db_session.flush()
    token = generate_session_token()
    db_session.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    db_session.commit()

    set_cookie(client, SESSION_COOKIE, token)

    assert not is_logged_in(client)


def test_logged_in_user_is_redirected_away_from_login_and_register(client: TestClient) -> None:
    register(client)

    for path in ("/login", "/register"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].endswith("/")


# --- CSRF -------------------------------------------------------------------------------


def test_post_without_csrf_token_is_rejected(client: TestClient, db_session: Session) -> None:
    client.get("/register")  # receives the CSRF cookie, but the form field is missing

    response = client.post(
        "/register",
        data={"email": EMAIL, "password": PASSWORD, "password_confirm": PASSWORD},
    )

    assert response.status_code == 403
    assert count(db_session, User) == 0


def test_post_with_token_not_matching_cookie_is_rejected(client: TestClient) -> None:
    client.get("/login")
    forged = create_csrf_token("guessed-secret", None)

    response = client.post(
        "/login", data={"email": EMAIL, "password": PASSWORD, "csrf_token": forged}
    )

    assert response.status_code == 403


def test_csrf_token_from_before_login_cannot_be_used_after_login(
    client: TestClient, db_session: Session
) -> None:
    anonymous_token = csrf_token_from(client, "/login")
    register(client)

    # Even with cookie and form field equal, the token is bound to the anonymous session.
    set_cookie(client, CSRF_COOKIE, anonymous_token)
    response = client.post("/logout", data={"csrf_token": anonymous_token})

    assert response.status_code == 403
    assert count(db_session, UserSession) == 1


def test_csrf_token_can_be_sent_in_header(client: TestClient) -> None:
    register(client)
    token = csrf_token_from(client, "/")

    response = client.post("/logout", headers={"X-CSRF-Token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert not is_logged_in(client)
