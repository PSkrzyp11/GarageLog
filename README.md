# GarageLog

Aplikacja webowa do prowadzenia historii serwisowej samochodów i analizowania kosztów ich utrzymania.

> Projekt w budowie — obecnie etap 2 (konta użytkowników: rejestracja, logowanie, sesje, CSRF).

## Stack

Python 3.12+, FastAPI, Jinja2, PostgreSQL, SQLAlchemy 2, Alembic, Docker Compose, pytest, ruff, GitHub Actions, uv.

## Uruchomienie w Dockerze

```bash
cp .env.example .env
docker compose up --build
```

Kontener aplikacji przy starcie sam wykonuje migracje bazy (`alembic upgrade head`).

Aplikacja: <http://127.0.0.1:8000>, health check: <http://127.0.0.1:8000/health>.

## Uruchomienie lokalne (development)

Wymaga [uv](https://docs.astral.sh/uv/) i Dockera (dla PostgreSQL).

```bash
uv sync
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --reload
```

## Migracje bazy

```bash
uv run alembic revision --autogenerate -m "opis zmiany"   # po zmianie app/models.py
uv run alembic upgrade head
uv run alembic check                                     # czy modele zgadzają się z migracjami
```

Wygenerowaną migrację zawsze trzeba przejrzeć przed commitem.

## Bezpieczeństwo kont

- Hasła hashowane algorytmem Argon2id; nieudane logowanie nie zdradza, czy konto istnieje.
- Sesje po stronie serwera: w ciasteczku (`HttpOnly`, `SameSite=Lax`, `Secure` w produkcji)
  jest losowy token, a w bazie tylko jego skrót SHA-256. Wylogowanie usuwa sesję z bazy;
  sesja wygasa po 14 dniach; logowanie zawsze tworzy nowy token.
- Ochrona CSRF dla każdego żądania POST: podpisany token (HMAC z `SECRET_KEY`) w ciasteczku
  i w polu formularza, powiązany z bieżącą sesją.
- Nagłówki bezpieczeństwa: Content-Security-Policy, `X-Frame-Options`, `X-Content-Type-Options`,
  `Referrer-Policy`.

Szczegóły i uzasadnienia: [`app/security.py`](app/security.py).

## Testy i jakość kodu

Testy integracyjne używają prawdziwego PostgreSQL (`docker compose up -d db`). Przy każdym
uruchomieniu tworzą od zera osobną bazę `garagelog_test` i wykonują na niej migracje; każdy test
działa w transakcji wycofywanej na końcu, więc testy nie widzą swoich danych.

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```
