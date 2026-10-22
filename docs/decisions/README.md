# Decyzje projektowe (ADR)

Krótkie notatki „Architecture Decision Record”: jaki był problem, co wybrałem, co z tego
wynika. Każda opisuje jedną decyzję, którą trudno odczytać z samego kodu.

| Nr | Decyzja |
|---|---|
| [0001](0001-ssr-with-htmx.md) | Strony renderowane na serwerze + HTMX zamiast SPA |
| [0002](0002-server-side-sessions.md) | Sesje w bazie zamiast JWT |
| [0003](0003-derived-odometer.md) | Aktualny przebieg jest wyliczany, nie zapisywany |
| [0004](0004-full-to-full-consumption.md) | Spalanie metodą „od pełnego do pełnego baku” |
| [0005](0005-money-as-numeric.md) | Kwoty jako `NUMERIC` / `Decimal`, nigdy `float` |
| [0006](0006-tests-on-real-postgres.md) | Testy na prawdziwym PostgreSQL z wycofywaną transakcją |
| [0007](0007-charts-with-chartjs.md) | Wykresy w Chart.js, dane z serwera w atrybucie `data-chart` |
| [0008](0008-recurring-reminders.md) | Przypomnienie cykliczne tworzy nowe przypomnienie po wykonaniu |
