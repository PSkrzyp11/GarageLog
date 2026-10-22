# 0008. Przypomnienie cykliczne tworzy nowe przypomnienie po wykonaniu

## Kontekst

Większość prac przy aucie się powtarza: olej co rok lub 15 000 km, badanie techniczne i OC
co rok. Wcześniej po wykonaniu trzeba było ręcznie dodać następne przypomnienie. Były dwie
drogi: przy „wykonane” przesuwać termin istniejącego przypomnienia albo tworzyć nowe.

## Decyzja

- Przypomnienie ma opcjonalne `repeat_months` (1–120) i `repeat_km`. Oznaczenie go jako
  wykonane zapisuje `completed_at` i tworzy **nowe** przypomnienie z tym samym tytułem,
  notatkami i interwałem.
- Następny termin liczy się od **dnia wykonania i aktualnego przebiegu**, nie od starego
  terminu: olej wymieniony 2 000 km po terminie i tak wystarczy na pełne 15 000 km.
  Obliczenia są w czystych funkcjach (`add_months`, `next_due` w `app/stats.py`);
  31 stycznia + 1 miesiąc to 28 (lub 29) lutego.
- Nowe przypomnienie pamięta, z którego powstało (`created_from_id`). „Przywróć” (cofnięcie
  pomyłkowego kliknięcia) usuwa je, chyba że zostało już wykonane.
- Klucz obcy ma `ON DELETE SET NULL`: usunięcie starego przypomnienia z historii nie usuwa
  następnego.

## Konsekwencje

- \+ Historia wykonanych prac zostaje („Ostatnio wykonane”), a lista aktywnych pokazuje
  od razu następny termin.
- \+ Cofnięcie pomyłki nie zostawia podwójnych przypomnień.
- − Termin według przebiegu liczy się od ostatniego przebiegu zapisanego w aplikacji; jeśli
  dawno nie było wpisu, następny termin wyjdzie trochę za wcześnie (można go poprawić).
- − Przypomnienie powtarzane tylko według przebiegu nie powstanie dla auta bez żadnego
  zapisanego przebiegu (w praktyce się nie zdarza: przebieg podaje się przy dodaniu auta).
