# 0003. Aktualny przebieg jest wyliczany, nie zapisywany

## Kontekst

Przebieg pojawia się w trzech miejscach: przy tankowaniu, przy wpisie serwisowym (opcjonalnie)
i jako osobny odczyt licznika. Kusi kolumna `cars.current_odometer_km`, ale wtedy każda
edycja lub usunięcie wpisu musiałaby ją aktualizować — klasyczne źródło rozjechanych danych
(„w historii jest 120 000 km, a w nagłówku 125 000”).

## Decyzja

- Każdy przebieg jest zapisany **raz**, przy zdarzeniu, którego dotyczy.
- Aktualny przebieg to największa z tych wartości (`UNION ALL` trzech tabel), liczona przy
  odczycie. Pulpit pobiera przebiegi wszystkich aut jednym zapytaniem.
- Spójność pilnuje reguła: **przebieg nie może maleć wraz z datą**. Nowy wpis jest odrzucany,
  jeśli wcześniejszy wpis ma większy przebieg albo późniejszy — mniejszy. Wpisów z tego samego
  dnia nie porównujemy (kolejność w ciągu dnia jest nieznana). Komunikat wskazuje konkretny
  konfliktowy wpis. Reguła to czyste funkcje w `app/odometer.py`.

## Konsekwencje

- \+ Po edycji czy usunięciu wpisu nie ma czego przeliczać — nic się nie rozjedzie.
- \+ Można dopisywać historię w dowolnej kolejności (stare faktury).
- − Wymiana licznika (cofnięcie przebiegu) nie jest obsługiwana — opisane jako ograniczenie.
- − Dwa jednoczesne zapisy z dwóch kart przeglądarki nie są blokowane (przy jednym
  użytkowniku na auto akceptowalne).
