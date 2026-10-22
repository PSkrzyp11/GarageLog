# GarageLog

[![CI](https://github.com/PSkrzyp11/GarageLog/actions/workflows/ci.yml/badge.svg)](https://github.com/PSkrzyp11/GarageLog/actions/workflows/ci.yml)

Aplikacja webowa do prowadzenia historii serwisowej samochodów i analizowania kosztów ich
utrzymania: tankowania, naprawy, przeglądy, koszt na kilometr, spalanie (także z LPG)
i przypomnienia o terminach.

Projekt portfolio: mały, kompletny monolit w Pythonie, w którym każdą decyzję da się
uzasadnić — od modelu danych po kontrolę dostępu.

![Pulpit: zaległe i zbliżające się przypomnienia, auta z przebiegiem i wydatkami w bieżącym roku](docs/screenshots/dashboard.png)

| Historia auta | Koszty i spalanie (benzyna + LPG) |
|---|---|
| ![Oś czasu tankowań i wpisów serwisowych z filtrem](docs/screenshots/history.png) | ![Koszt całkowity, koszt na km, podział na kategorie, spalanie z tabelą odcinków](docs/screenshots/costs.png) |
| **Walidacja przebiegu** | **Telefon (390 px)** |
| ![Komunikat: późniejszy wpis ma mniejszy przebieg](docs/screenshots/validation.png) | ![Podsumowanie kosztów na telefonie](docs/screenshots/mobile-costs.png) |

## Co potrafi

- **Konta** — rejestracja i logowanie; każdy widzi wyłącznie swoje auta i dane.
- **Auta** — kilka aut na konto, paliwo główne + opcjonalna instalacja LPG.
- **Historia** — tankowania (pełne / częściowe / po pominiętym tankowaniu), serwis i inne
  wydatki, odczyty licznika; wspólna oś czasu z filtrem rodzaju i roku.
- **Spójny przebieg** — wpisy można dopisywać w dowolnej kolejności (stare faktury), ale
  przebieg nie może maleć z upływem czasu; komunikat wskazuje konfliktowy wpis.
- **Koszty** — koszt całkowity, paliwo, podział na kategorie i koszt na kilometr za wybrany
  okres; zamiast mylących liczb — „za mało danych” z wyjaśnieniem.
- **Spalanie** — metodą „od pełnego do pełnego baku”, osobno dla każdego paliwa, z tabelą
  odcinków, z których wynika.
- **Przypomnienia** — według daty, przebiegu albo obu („co nastąpi wcześniej”), z sekcją
  „Do zrobienia” na pulpicie.
- **Eksport CSV** — pod polskiego Excela, odporny na CSV injection.
- **Interfejs** — po polsku, responsywny, działa bez JavaScriptu; HTMX usprawnia filtry
  i akcje w miejscu.

## Stack

| | |
|---|---|
| Backend | Python 3.12+, FastAPI (endpointy synchroniczne), Pydantic |
| Baza | PostgreSQL 18, SQLAlchemy 2.0, Alembic |
| Interfejs | Jinja2 (renderowanie na serwerze), własny CSS, HTMX 2 |
| Bezpieczeństwo | Argon2id, sesje w bazie, CSRF, CSP |
| Jakość | pytest (testy na prawdziwym PostgreSQL), ruff, GitHub Actions |
| Uruchamianie | Docker Compose, uv |

Celowo **bez** SPA, mikroserwisów, kolejek i zewnętrznych usług — patrz
[decyzje projektowe](docs/decisions/README.md).

## Szybki start (Docker)

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec app python -m scripts.seed_demo
```

Ostatnie polecenie tworzy konto `demo@example.com` z dwoma autami i około dwuletnią,
fikcyjną historią, a hasło wypisuje raz w konsoli (nie jest nigdzie zapisywane). Własne
hasło: `docker compose exec -e DEMO_PASSWORD=... app python -m scripts.seed_demo --reset`.

Aplikacja: <http://127.0.0.1:8000>. Kontener sam wykonuje migracje przy starcie.

## Development

Wymaga [uv](https://docs.astral.sh/uv/) i Dockera (dla PostgreSQL).

```bash
uv sync
docker compose up -d db
uv run alembic upgrade head
uv run uvicorn app.main:create_app --factory --reload
```

Migracje:

```bash
uv run alembic revision --autogenerate -m "opis zmiany"   # po zmianie app/models.py
uv run alembic upgrade head
uv run alembic check                                     # czy modele zgadzają się z migracjami
```

Testy i jakość kodu:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Testy integracyjne tworzą przy każdym uruchomieniu osobną bazę `garagelog_test`, migrują ją
Alembikiem, a każdy test działa w wycofywanej transakcji
([ADR 0006](docs/decisions/0006-tests-on-real-postgres.md)).

## Jak to działa

```mermaid
flowchart LR
    B[Przeglądarka] -->|formularz albo HTMX| R[Trasy<br/>app/routes]
    R -->|CurrentUser, OwnedCar, CSRF| D[Zależności<br/>app/deps.py]
    R --> S[Serwisy<br/>app/services]
    S --> F[Czyste funkcje<br/>stats.py, odometer.py]
    S --> DB[(PostgreSQL)]
    R -->|HTML lub fragment| B
```

- **Trasy** obsługują HTTP i decydują o commicie; **serwisy** zawierają reguły wymagające
  bazy; **czyste funkcje** (koszty, spalanie, statusy, spójność przebiegu) nie dotykają bazy
  i są testowane jednostkowo.
- Kontrola dostępu jest częścią zapytania: `WHERE cars.id = :id AND cars.user_id = :user`.
  Cudze i nieistniejące zasoby dają to samo 404.
- Nic nie jest liczone „z góry”: aktualny przebieg, sumy i statusy przypomnień powstają przy
  odczycie, więc edycja wpisu nie może zostawić nieaktualnych danych.

Więcej: [architektura, droga żądania i model danych](docs/architecture.md).

## Definicje obliczeń

| Wartość | Definicja |
|---|---|
| Koszt całkowity | Suma tankowań i pozostałych wydatków z okresu. Bez ceny zakupu i utraty wartości. |
| Koszt na kilometr | Koszt całkowity ÷ przejechany dystans (najwyższy przebieg w okresie minus ostatni sprzed okresu). Pokazywany od 1 000 km. |
| Spalanie | Σ litrów ÷ Σ km z odcinków między tankowaniami do pełna tego samego paliwa; odcinki z pominiętym tankowaniem są pomijane ([ADR 0004](docs/decisions/0004-full-to-full-consumption.md)). |
| Koszt paliwa na km | Koszt tankowań w tych samych odcinkach ÷ ich dystans; dla auta z LPG suma obu paliw. |
| Przypomnienie zaległe | Minęła data albo przebieg osiągnął wartość docelową — co nastąpi wcześniej. „Wkrótce”: do 30 dni lub 1 000 km. |

Kwoty są liczone na `Decimal` i zapisywane jako `NUMERIC` ([ADR 0005](docs/decisions/0005-money-as-numeric.md)).

## Bezpieczeństwo

- Hasła: Argon2id; nieudane logowanie nie zdradza, czy konto istnieje (także czasem odpowiedzi).
- Sesje w bazie: w ciasteczku (`HttpOnly`, `SameSite=Lax`, `Secure` w produkcji) losowy token,
  w bazie tylko jego skrót SHA-256; nowy token przy każdym logowaniu
  ([ADR 0002](docs/decisions/0002-server-side-sessions.md)).
- CSRF: podpisany token powiązany z sesją, sprawdzany dla **każdego** żądania zmieniającego dane.
- Kontrola dostępu przetestowana dla każdej trasy z `{car_id}`; test kontrolny nie pozwala dodać
  trasy bez tego testu.
- Nagłówki: Content-Security-Policy (`default-src 'self'`, bez skryptów inline),
  `X-Frame-Options`, `nosniff`, `Referrer-Policy`.
- Eksport CSV: tekst zaczynający się od `=`, `+`, `-`, `@` nie stanie się formułą w Excelu.
- Sekrety tylko w zmiennych środowiskowych (`.env` poza repozytorium); w produkcji aplikacja
  nie wystartuje z domyślnym `SECRET_KEY`.

## Interfejs

Strony są renderowane na serwerze i działają bez JavaScriptu. [HTMX](https://htmx.org) 2.0.11
tylko je usprawnia ([ADR 0001](docs/decisions/0001-ssr-with-htmx.md)). Plik
`app/static/js/htmx.min.js` pochodzi z paczki npm `htmx.org@2.0.11`
(SHA-256 `d6fdc75f…4000f717`) i jest serwowany z naszej domeny. Pliki statyczne mają w adresie
skrót zawartości (`app.css?v=…`), więc przeglądarka może je trzymać przez rok bez ryzyka
nieaktualnego stylu.

## Ograniczenia

Świadomie poza zakresem albo uproszczone:

- jedna waluta (PLN) i jednostki metryczne;
- brak aut elektrycznych i ładowania;
- wymiana licznika (cofnięcie przebiegu) nie jest obsługiwana;
- przypomnienia jednorazowe (bez „co 15 000 km”) i tylko w aplikacji — bez e-maili;
- brak resetu hasła, weryfikacji e-maila i usuwania konta z poziomu aplikacji;
- formularz rejestracji zdradza, że e-mail jest już zajęty (bez potwierdzania e-maila nie da
  się tego uniknąć — formularz logowania niczego nie zdradza);
- brak limitu prób logowania — potrzebny przed publicznym wdrożeniem;
- dwa jednoczesne zapisy z dwóch kart przeglądarki nie są blokowane (reguła przebiegu może
  wtedy przepuścić konflikt);
- koszt nie obejmuje ceny zakupu ani utraty wartości auta;
- domyślnie aplikacja lokalna (Docker Compose) — publiczne demo nie jest wdrożone.

## Możliwe dalsze kroki

Przypomnienia cykliczne, archiwizacja sprzedanego auta, wykresy kosztów miesięcznych,
import CSV, reset hasła, publiczne demo z HTTPS i limitem logowań.

## Licencja

[MIT](LICENSE)
