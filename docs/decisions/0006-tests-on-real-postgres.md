# 0006. Testy na prawdziwym PostgreSQL z wycofywaną transakcją

## Kontekst

Testy integracyjne na SQLite są szybkie w konfiguracji, ale SQLite inaczej traktuje typy,
`CHECK`, `NUMERIC`, strefy czasowe i kaskady. Test, który przechodzi na SQLite, może nie
przejść na produkcyjnym PostgreSQL — i odwrotnie. Duża część reguł aplikacji (unikalność,
kaskady, ograniczenia) jest właśnie w bazie.

## Decyzja

- Osobna baza `garagelog_test` jest przy każdym uruchomieniu tworzona od zera
  i migrowana **Alembikiem** — testy sprawdzają więc też migracje. Fikstura odmawia usunięcia
  bazy, której nazwa nie kończy się na `_test`.
- Każdy test działa w transakcji wycofywanej na końcu
  (`join_transaction_mode="create_savepoint"`), więc kod może wywoływać `commit()`, a testy
  nie widzą swoich danych.
- Osobny test porównuje modele z migracjami (`compare_metadata`), a CI dodatkowo uruchamia
  `alembic check`.
- Kontrola dostępu jest testowana parametrycznie dla **każdej** trasy z `{car_id}`; test
  kontrolny porównuje tę listę z routerem, więc nowej trasy nie da się dodać bez testu.

## Konsekwencje

- \+ Testy łapią błędy, które SQLite by przepuściło (np. nazwane ograniczenia `CHECK`).
- \+ Cały zestaw (~370 testów) trwa kilkanaście sekund.
- − Do testów potrzebny jest działający PostgreSQL (`docker compose up -d db` lokalnie,
  service container w CI).
