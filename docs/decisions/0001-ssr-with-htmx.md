# 0001. Strony renderowane na serwerze + HTMX zamiast SPA

## Kontekst

Aplikacja to głównie formularze i listy. Jedna osoba ma ją rozumieć w całości, a projekt ma
uczyć backendu i pracy z bazą danych. Osobny frontend w React/Vue oznaczałby drugie
repozytorium (albo drugi build), API JSON do zaprojektowania i utrzymania, uwierzytelnianie
tokenami w przeglądarce i dwa razy więcej miejsc na błędy walidacji.

## Decyzja

HTML jest renderowany na serwerze (FastAPI + Jinja2). Każda akcja jest zwykłym formularzem
z wzorcem POST → przekierowanie → GET. [HTMX](https://htmx.org) dodaje kilka interakcji bez
przeładowania strony (filtry, „wykonane”, usuwanie w wierszu), ale strona działa bez niego.

- Trasa zwraca fragment, gdy przychodzi nagłówek `HX-Request`, a pełną stronę w każdym innym
  przypadku (także przy przywracaniu historii przyciskiem „Wstecz”). Odpowiedzi mają
  `Vary: HX-Request`.
- `htmx.min.js` jest w repozytorium, a nie z CDN, więc Content-Security-Policy dopuszcza tylko
  własną domenę. Konfiguracja wyłącza `eval`, wstrzykiwane style i zapisywanie stron
  w `localStorage`.

## Konsekwencje

- \+ Jeden język szablonów, jedna walidacja (po stronie serwera), brak API do wersjonowania.
- \+ Bez JavaScriptu wszystko działa; testy integracyjne sprawdzają zwykłe formularze.
- \+ Mało kodu klienta do utrzymania (zero własnego JS).
- − Mniej „płynny” interfejs niż w SPA; bardziej złożone ekrany (np. wykresy) wymagałyby
  osobnej decyzji.
- − Część logiki „co odświeżyć po akcji” leży w trasach (fragmenty, `hx-swap-oob`).
