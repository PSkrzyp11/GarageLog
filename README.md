# GarageLog

Aplikacja webowa do prowadzenia historii serwisowej samochodów i analizowania kosztów ich utrzymania.

> Projekt w budowie — obecnie etap 0 (szkielet: FastAPI, Docker Compose, CI).

## Stack

Python 3.12+, FastAPI, Jinja2, PostgreSQL, Docker Compose, pytest, ruff, GitHub Actions, uv.

## Uruchomienie w Dockerze

```bash
cp .env.example .env
docker compose up --build
```

Aplikacja: <http://127.0.0.1:8000>, health check: <http://127.0.0.1:8000/health>.

## Uruchomienie lokalne (development)

Wymaga [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run uvicorn app.main:create_app --factory --reload
```

## Testy i jakość kodu

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```
