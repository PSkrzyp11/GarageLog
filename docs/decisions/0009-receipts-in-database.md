# 0009. Paragony w bazie, zdjęcia zapisywane od nowa

## Kontekst

Do tankowania można dołączyć zdjęcie albo PDF paragonu. Plik przysyła użytkownik, często
prosto z aparatu telefonu, więc trzeba zdecydować, gdzie go trzymać i jak go bezpiecznie
pokazywać. Zdjęcia z telefonu mają w metadanych EXIF m.in. współrzędne GPS miejsca zrobienia.

## Decyzja

- **Gdzie:** w PostgreSQL, w osobnej tabeli `fuel_receipts` (`bytea`), najwyżej jeden plik na
  tankowanie. Lista tankowań nigdy nie wczytuje plików. Codzienny `pg_dump` obejmuje je bez
  zmian w kopiach zapasowych, a usunięcie tankowania lub auta usuwa plik (`ON DELETE CASCADE`).
- **Typ pliku:** rozpoznawany po zawartości (Pillow / nagłówek `%PDF-`), nie po nazwie ani po
  typie podanym przez przeglądarkę.
- **Zdjęcia:** dekodowane i zapisywane od nowa jako JPEG (do 2000 px). Znikają wszystkie
  metadane, w tym lokalizacja; obrót z EXIF jest wcześniej nakładany na piksele. Nawet
  spreparowany plik „udający” zdjęcie nie dotrze do przeglądarki — serwowane są tylko piksele
  zakodowane przez aplikację. Odrzucane są „bomby dekompresyjne” (ponad 50 Mpx).
- **PDF:** zapisywany bez zmian, ale wydawany tylko do pobrania
  (`Content-Disposition: attachment`), nigdy jako strona tej witryny.
- **Rozmiar:** do 10 MB; większy limit treści żądania (zamiast 64 KB) dotyczy tylko dwóch
  formularzy tankowania.
- Pobranie pliku przechodzi przez te same zależności co reszta (`OwnedFuelEntry`), więc obcy
  paragon daje 404 — trasa jest na liście testu IDOR.

## Konsekwencje

- \+ Jedno miejsce danych: kopia bazy to kopia wszystkiego, bez synchronizowania katalogów.
- \+ Prywatność: zdjęcie nie zdradza, gdzie było zrobione.
- − Baza rośnie (zdjęcie to ok. 200–500 KB); przy setkach paragonów to nadal mało, przy
  dziesiątkach tysięcy lepszy byłby osobny magazyn plików.
- − Oryginał zdjęcia nie jest przechowywany — tylko zmniejszona kopia.
- − Zdjęcia HEIC (domyślne na iPhonie) przyjmujemy tylko wtedy, gdy przeglądarka przy wysyłaniu
  zamieni je na JPEG (Safari robi to sama).
