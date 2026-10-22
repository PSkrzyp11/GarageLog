# 0005. Kwoty jako `NUMERIC` / `Decimal`, nigdy `float`

## Kontekst

Liczby zmiennoprzecinkowe nie zapisują dokładnie ułamków dziesiętnych: w Pythonie
`0.1 + 0.2 == 0.30000000000000004`. Przy sumowaniu setek tankowań błędy się kumulują
i suma „nie zgadza się co do grosza” z paragonami.

## Decyzja

- W bazie: `NUMERIC(10,2)` dla kwot, `NUMERIC(6,2)` dla litrów, `INTEGER` dla kilometrów.
- W Pythonie: `Decimal` od formularza (parsowanie „1 234,56”) do wyniku; zaokrąglenie
  `ROUND_HALF_UP` tylko przy wyświetlaniu i **raz** na końcu obliczenia (np. łączny koszt
  paliwa na km sumuje dokładne wartości, a nie zaokrąglone).
- Jedna waluta (PLN) — zapisana w nazwie kolumny (`cost_pln`), zamiast kolumny waluty,
  której nikt by nie używał.
- Cena za litr nie jest zapisywana; wynika z kwoty i litrów (jeden fakt, jedno miejsce).

## Konsekwencje

- \+ Sumy zgadzają się co do grosza (testy porównują je z ręcznie policzonymi).
- − Obsługa wielu walut wymagałaby migracji i decyzji o kursach — świadomie poza zakresem.
