# Architektura

Jedna aplikacja (monolit) i jedna baza. Trzy warstwy, bez osobnej warstwy repozytoriów —
`Session` z SQLAlchemy już nią jest.

| Warstwa | Gdzie | Za co odpowiada |
|---|---|---|
| Trasy | `app/routes/` | HTTP: formularz → walidacja (Pydantic) → serwis → szablon albo przekierowanie; commit transakcji |
| Serwisy | `app/services/` | Reguły wymagające bazy, zapytania SQLAlchemy (zawsze w obrębie auta, którego właściciela już sprawdzono) |
| Czyste funkcje | `app/stats.py`, `app/odometer.py` | Koszty, spalanie, statusy przypomnień, spójność przebiegu — bez bazy, łatwe do testowania |
| Bezpieczeństwo | `app/security.py`, `app/deps.py` | Hasła, sesje, CSRF, nagłówki; `CurrentUser` i `get_owned_car` jako punkt kontroli dostępu |

## Droga żądania

```mermaid
sequenceDiagram
    autonumber
    actor U as Przeglądarka
    participant M as Middleware
    participant D as Zależności (deps)
    participant R as Trasa
    participant S as Serwis
    participant DB as PostgreSQL

    U->>M: POST /cars/7/fuel/new (formularz + csrf_token)
    M->>D: verify_csrf — token z ciasteczka = token z formularza, podpis HMAC, ta sama sesja
    D->>DB: sesja z ciasteczka (skrót SHA-256) → użytkownik
    D->>DB: get_owned_car: WHERE id = 7 AND user_id = :użytkownik
    Note over D: cudze lub nieistniejące auto → 404
    D->>R: CurrentUser, OwnedCar, FormData
    R->>R: walidacja formularza (Pydantic, polskie komunikaty)
    R->>S: create_fuel_entry(car, form)
    S->>DB: reguły: paliwo pasuje do auta, przebieg nie maleje
    S-->>R: OK albo EntryValidationError(pole, komunikat)
    R->>DB: COMMIT
    R-->>M: 303 → /cars/7 (albo fragment HTML dla HTMX)
    M-->>U: + nagłówki bezpieczeństwa (CSP, X-Frame-Options…)
```

## Model danych

```mermaid
erDiagram
    users ||--o{ sessions : "ma"
    users ||--o{ cars : "ma"
    cars ||--o{ odometer_readings : "ma"
    cars ||--o{ service_entries : "ma"
    cars ||--o{ fuel_entries : "ma"
    cars ||--o{ reminders : "ma"

    users {
        int id PK
        varchar email UK "małe litery (CHECK)"
        varchar password_hash "Argon2id"
    }
    sessions {
        int id PK
        int user_id FK
        varchar token_hash UK "SHA-256"
        timestamptz expires_at
    }
    cars {
        int id PK
        int user_id FK
        varchar name "UNIQUE z user_id"
        varchar primary_fuel "petrol | diesel"
        bool has_lpg
    }
    odometer_readings {
        int id PK
        int car_id FK
        date date
        int odometer_km
    }
    service_entries {
        int id PK
        int car_id FK
        date date
        int odometer_km "opcjonalny"
        varchar category
        numeric cost_pln "NUMERIC(10,2)"
    }
    fuel_entries {
        int id PK
        int car_id FK
        date date
        int odometer_km
        varchar fuel_type "petrol | diesel | lpg"
        numeric liters "NUMERIC(6,2)"
        numeric total_cost_pln
        bool is_full_tank
        bool missed_previous
    }
    reminders {
        int id PK
        int car_id FK
        date due_date "data i/lub przebieg (CHECK)"
        int due_odometer_km
        timestamptz completed_at
    }
```

Wszystkie relacje mają `ON DELETE CASCADE` w bazie: usunięcie auta usuwa jego historię,
usunięcie konta — wszystko. Nie ma kolumn z sumami ani aktualnym przebiegiem: wszystkie
podsumowania są liczone przy odczycie ([ADR 0003](decisions/0003-derived-odometer.md)).

## Uruchamianie

```mermaid
flowchart LR
    B[Przeglądarka] -->|HTTP, 127.0.0.1:8000| A[kontener app<br/>uvicorn + FastAPI]
    A -->|psycopg| P[(kontener db<br/>PostgreSQL 18)]
    A -. "przy starcie:<br/>alembic upgrade head" .-> P
```

`docker compose up` uruchamia oba kontenery; aplikacja startuje dopiero, gdy baza zgłosi
gotowość, i przed startem wykonuje migracje. Porty są dostępne tylko z `127.0.0.1`.
