from app.security import (
    create_csrf_token,
    hash_password,
    hash_session_token,
    is_csrf_token_valid,
    verify_password,
)

SECRET = "test-secret-key"


def test_password_hash_is_argon2id_and_verifies() -> None:
    password_hash = hash_password("correct horse battery")

    assert password_hash.startswith("$argon2id$")
    assert "correct horse battery" not in password_hash
    assert verify_password(password_hash, "correct horse battery")


def test_wrong_password_does_not_verify() -> None:
    assert not verify_password(hash_password("correct horse battery"), "wrong password")


def test_hashing_the_same_password_twice_gives_different_hashes() -> None:
    # A random salt per hash: equal passwords are not visible as equal hashes.
    assert hash_password("same password") != hash_password("same password")


def test_malformed_hash_is_rejected_instead_of_raising() -> None:
    assert not verify_password("not-an-argon2-hash", "anything")


def test_session_token_hash_is_sha256_hex_and_deterministic() -> None:
    token_hash = hash_session_token("some-token")

    assert len(token_hash) == 64
    assert token_hash == hash_session_token("some-token")
    assert token_hash != hash_session_token("other-token")


def test_csrf_token_is_valid_for_its_own_session() -> None:
    token = create_csrf_token(SECRET, "session-a")

    assert is_csrf_token_valid(token, SECRET, "session-a")


def test_csrf_token_is_rejected_for_another_session() -> None:
    token = create_csrf_token(SECRET, "session-a")

    assert not is_csrf_token_valid(token, SECRET, "session-b")
    assert not is_csrf_token_valid(token, SECRET, None)


def test_anonymous_csrf_token_is_rejected_after_login() -> None:
    token = create_csrf_token(SECRET, None)

    assert is_csrf_token_valid(token, SECRET, None)
    assert not is_csrf_token_valid(token, SECRET, "new-session")


def test_csrf_token_signed_with_another_key_is_rejected() -> None:
    token = create_csrf_token("other-secret", None)

    assert not is_csrf_token_valid(token, SECRET, None)


def test_tampered_or_malformed_csrf_token_is_rejected() -> None:
    nonce, _, signature = create_csrf_token(SECRET, None).partition(".")

    assert not is_csrf_token_valid(f"{nonce}x.{signature}", SECRET, None)
    assert not is_csrf_token_valid("no-signature", SECRET, None)
    assert not is_csrf_token_valid("", SECRET, None)
