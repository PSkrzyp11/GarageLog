# 0004. Spalanie metodą „od pełnego do pełnego baku”

## Kontekst

Naiwne „litry z tankowania ÷ km od poprzedniego tankowania” daje bzdury: po dolaniu 20 l do
połowy baku wychodzi zaniżone spalanie, a po następnym tankowaniu do pełna — zawyżone.
Wynik, który wygląda wiarygodnie, ale nim nie jest, jest gorszy niż brak wyniku.

## Decyzja

Spalanie liczymy tylko między dwoma tankowaniami **do pełna** tego samego paliwa
(`app/stats.py`, `full_to_full_segments`):

- litry odcinka = wszystko dolane po pierwszym pełnym tankowaniu, łącznie z częściowymi po
  drodze i z tankowaniem zamykającym; litrów pierwszego pełnego tankowania nie liczymy;
- tankowania porządkujemy po **przebiegu** (fizyczna kolejność), nie po wpisanej dacie;
- odcinek zawierający tankowanie oznaczone „pominąłem wcześniejsze tankowanie” jest
  pomijany — część litrów jest nieznana;
- średnia jest **ważona dystansem**: Σ litrów ÷ Σ km, a nie średnia z odcinków (krótki
  odcinek miejski nie może ważyć tyle co długa trasa);
- każde paliwo osobno — auto z LPG ma osobne spalanie LPG i benzyny;
- gdy brakuje danych, aplikacja mówi dlaczego (za mało pełnych tankowań, pominięte
  tankowanie, brak zakończonego odcinka w okresie), zamiast pokazywać liczbę.

## Konsekwencje

- \+ Wynik zgadza się z tym, jak spalanie liczą kierowcy, i da się go zweryfikować — strona
  pokazuje tabelę odcinków, z których wynika.
- \+ Logika to czyste funkcje ze 100% pokryciem testami (w tym przykład z planu:
  pełne → 20 l → 30 l pełne na 800 km = 6,25 l/100 km).
- − Użytkownik musi zaznaczać „do pełna” i „pominięte tankowanie”; bez tego wynik będzie
  mniej dokładny albo go nie będzie.
