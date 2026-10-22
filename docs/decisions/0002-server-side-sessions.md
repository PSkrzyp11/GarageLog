# 0002. Sesje w bazie zamiast JWT

## Kontekst

Użytkownik loguje się raz i pracuje w przeglądarce. Potrzebne są: prawdziwe wylogowanie,
możliwość unieważnienia sesji i ochrona przed kradzieżą tokenu. FastAPI nie ma wbudowanych
sesji, więc tak czy inaczej trzeba coś napisać samemu.

## Decyzja

- W ciasteczku `session` jest losowy token (`secrets.token_urlsafe(32)`); ciasteczko jest
  `HttpOnly`, `SameSite=Lax`, a w produkcji `Secure`.
- W tabeli `sessions` zapisany jest tylko **skrót SHA-256** tokenu i data wygaśnięcia
  (14 dni). Wyciek bazy nie daje gotowych sesji.
- Logowanie zawsze tworzy nowy token (ochrona przed *session fixation*); wylogowanie usuwa
  wiersz z bazy.
- Formularze chroni podpisany token CSRF (HMAC z `SECRET_KEY`) powiązany z bieżącą sesją,
  sprawdzany przez zależność zarejestrowaną dla całej aplikacji.

## Rozważone: JWT

JWT ma sens, gdy wiele usług musi weryfikować tożsamość bez wspólnej bazy. Tu jest jedna
aplikacja i jedna baza. JWT nie da się unieważnić przed wygaśnięciem bez dodatkowej listy
zablokowanych tokenów — czyli i tak skończyłoby się na tabeli w bazie, tylko bardziej
skomplikowanej.

## Konsekwencje

- \+ Wylogowanie i unieważnienie sesji działają od razu.
- \+ Prosty, w pełni przetestowany kod w jednym module (`app/security.py`).
- − Jedno zapytanie do bazy przy każdym żądaniu (przy tej skali bez znaczenia).
- − Przy wielu serwerach wszystkie muszą widzieć tę samą bazę (tak jest i tak).
