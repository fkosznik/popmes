# Architektura POPMES 0.1

## Stos

- Python 3.12, Django 5.2, Django REST Framework; dokładne wersje w backend/requirements.txt.
- TypeScript, React, Vite; wersje zależności utrwalone w frontend/package-lock.json.
- PostgreSQL 17; w rozwoju można jawnie włączyć SQLite.
- Nginx serwuje zbudowany interfejs i przekazuje /api/ do Gunicorn.
- Docker Compose: frontend, backend, database; opcjonalnie caddy dla HTTPS.

React komunikuje się przez względne /api/, więc frontend i API mają ten sam origin. Sesja jest w ciasteczku HttpOnly; zapisy wymagają tokenu CSRF. Etykiety pobierane są przez endpoint uwierzytelniony, bez publicznego serwowania katalogu media. Fonty są w bundlu i aplikacja nie pobiera ich z zewnętrznego serwisu.

## Moduły backendu

- models.py: encje, relacje, ograniczenia bazy.
- services.py: przejścia biznesowe i reguły masy/ilości.
- views.py: API, uwierzytelnianie, role, transakcje, idempotencja.
- serializers.py: walidacja katalogów.
- presentation.py: dane interfejsu i maskowanie dostępu według roli.
- management/commands: bootstrap, seed_catalog, seed_demo.
- tests.py: przepływ, korekty, etykiety, uprawnienia, CSRF, współbieżność PostgreSQL.

Jeden modułowy backend zachowuje transakcje między zamówieniem, partią i pakowaniem. Worker/broker nie są potrzebne do podstawowego obiegu.

## Model procesu

Zamówienie ma pozycje utrwalające produkt, gramaturę i instrukcję. Zatwierdzenie tworzy produkcję per smak i pakowanie per pozycja. Produkcja przyjmuje masę do partii; pakowanie tworzy ujemne ruchy partii i zwiększa liczbę dobrych sztuk.

Batch.available_g, Task.produced_g i Item.packed są saldami aktualizowanymi transakcyjnie; nie są bezpośrednio edytowalne przez API. Ruchy, raporty i korekty pozwalają odtworzyć powód zmiany. Dostępny zapas nie może być ujemny również na poziomie CHECK w bazie. Przepływ identyfikuje partie produktu gotowego, nie partie surowców.

Korekta oznacza pełne cofnięcie jednego raportu. Poprawne wykonanie zgłasza się nowym raportem. Przy błędnym zapisie pakowania masa może zostać jawnie przywrócona; przy wycofaniu rzeczywiście zapakowanego produktu pozostaje zużyta. Dzięki temu wycofanie sztuk nie tworzy fikcyjnego zapasu.

## Współbieżność i ponowienia

Wszystkie operacyjne zapisy przechodzą przez transaction.atomic i select_for_update na zamówieniu. Transfery blokują oba zamówienia w kolejności identyfikatorów, następnie partię. Stan zadania jest odczytywany po zdobyciu blokady. Taka kolejność chroni wspólną pulę masy, gdy kilku pracowników zapisuje raporty jednocześnie.

POST wymaga nagłówka Idempotency-Key z UUID. Pod blokadą konta użytkownika serwer sprawdza wcześniejszy wynik i skrót ścieżki/payloadu. Identyczne ponowienie zwraca wcześniejszy wynik; inne dane pod tym samym kluczem są odrzucane. Zapis wyniku i zmiany domenowe są w jednej transakcji. Dotyczy także uploadu, którego zawartość jest haszowana. Wyjątki: login i logout (osobne bezpieczne operacje sesji).

Edytowanie zamówienia wymaga wersji widocznej w formularzu. Każde zdarzenie podbija wersję; nieaktualny formularz zostaje odrzucony. Pełny snapshot /api/state/ odświeża UI co 5 s. To rozwiązanie na mały zakład; przy większej historii należy dodać paginację i ograniczyć snapshot do aktywnego zakresu.

## Główne endpointy

| Metoda i ścieżka /api/ | Funkcja |
|---|---|
| GET auth/me/ | Sesja oraz ustawienie ciasteczka CSRF |
| POST auth/login/, auth/logout/ | Logowanie i wylogowanie |
| GET state/ | Dane pulpitów zgodne z rolą |
| POST catalog/products/, variants/, customers/ | Utworzenie/edycja/archiwizacja |
| POST orders/save/ | Nowy zamówienie lub edycja szkicu; confirm=true zatwierdza |
| GET orders/{id}/ | Szczegóły, raporty i historia |
| POST orders/{id}/confirm/, amend/ | Zatwierdzenie lub zmiana ilości/terminu |
| POST orders/{id}/hold/, resume/, cancel/ | Blokada, wznowienie, anulowanie |
| POST orders/{id}/issue/, unissue/ | Wydanie i jawne cofnięcie wydania |
| POST orders/{id}/replenish/ | Produkcja uzupełniająca po odjęciu planu |
| POST tasks/{id}/start/, pause/, report/ | Czas pracy i raport wykonania |
| POST tasks/{id}/hold/, resume/, target/ | Problem, odblokowanie, cel produkcji |
| POST items/{id}/labels/ | Multipart upload file, do 20 MB |
| POST labels/{id}/approve/ | Zatwierdzenie najnowszej wersji |
| GET labels/{id}/download/ | Pobranie chronionego pliku |
| POST reports/{id}/correct/ | Audytowalne cofnięcie raportu |
| POST batches/{id}/move/ | Transfer całej dostępnej pozostałości lub rozchód |
| GET/POST users/ | Użytkownicy i role |
| GET health/ | Gotowość backendu i bazy |

Przykłady payloadów:

```json
{"customer_id":1,"due_at":"2026-12-01T14:00:00Z","items":[{"variant_id":1,"quantity":200}],"confirm":true}
```

```json
{"grams":"4000.000","waste_g":"100.000","note":"Produkt wystudzony"}
```

```json
{"units":100,"grams":"3100.000","waste_g":"100.000","allocations":[{"batch_id":1,"grams":"3100.000"}]}
```

API masy są w gramach; interfejs raportowania używa kilogramów. Pominięcie grams przy pakowaniu oznacza szacunek sztuki × gramatura. Pominięcie allocations włącza FIFO. Dostarczone allocations mogą wskazywać kilka partii z sumą równą zużyciu.

Daty zapisujemy jako świadome strefy UTC; interfejs prezentuje czas Europe/Warsaw. Aktywny czas stanowi sumę sesji pracowników — przy dwóch pracownikach równocześnie są to roboczominuty, nie czas kalendarzowy.
