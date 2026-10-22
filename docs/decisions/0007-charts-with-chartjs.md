# 0007. Wykresy w Chart.js, dane z serwera w atrybucie `data-chart`

## Kontekst

Strona kosztów miała pokazać wydatki miesięczne i cenę paliwa w czasie. Rozważane były dwie
drogi: wykresy SVG generowane w Pythonie (zero JavaScriptu) albo biblioteka JS. Aplikacja ma
ścisłą Content-Security-Policy (`default-src 'self'`: bez skryptów i stylów inline) i działa
bez JavaScriptu ([ADR 0001](0001-ssr-with-htmx.md)).

## Decyzja

- [Chart.js](https://www.chartjs.org) 4.5.1 (MIT) dołączony do repozytorium, jak htmx —
  z paczki npm `chart.js`, SHA-256 sprawdzony z drugim CDN. Najnowsza wersja (4.6.1) była
  wtedy wydana tego samego dnia, więc wybrana została poprzednia, sprawdzona w praktyce.
- Liczby liczy serwer (`app/stats.py`: `monthly_costs`, `fuel_prices`), a `app/charts.py`
  zamienia je na mały JSON wstawiany do `<canvas data-chart="…">`. Przeglądarka nie dostaje
  żadnego skryptu inline — `app/static/js/charts.js` czyta atrybut i rysuje wykres.
- Chart.js zmienia tylko `canvas.style` przez JavaScript (to CSP dopuszcza), nie wstawia
  `<style>` ani nie używa `eval` — CSP została bez zmian.
- Po zmianie okresu (HTMX) stare wykresy są niszczone (`htmx:beforeSwap`), a nowe rysowane
  (`htmx:load`).
- Każdy wykres ma obok tabelę „Dane wykresu” z tymi samymi liczbami: dla czytników ekranu
  i dla przeglądarek bez JavaScriptu (wtedy płótno wykresu jest ukryte).
- Biblioteka ładuje się tylko na stronie kosztów.

## Konsekwencje

- \+ Czytelne wykresy z dymkami i legendą bez pisania własnej logiki rysowania.
- \+ Obliczenia nadal są w czystych funkcjach i testowane jednostkowo; JavaScript tylko rysuje.
- − ~200 KB JavaScriptu więcej na stronie kosztów.
- − Bez JavaScriptu wykresów nie ma (zostaje tabela z danymi).
