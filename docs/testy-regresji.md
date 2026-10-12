# Testy regresji POPMES

Uruchomienie pełnego zestawu backendu na PostgreSQL:

```sh
docker compose exec -T backend python manage.py test core -v 2
```

Workflow `.github/workflows/ci.yml` uruchamia testy na pull requestach i przy zmianach main. Sprawdza także migracje, interfejs w Playwright i backup/restore. Błąd backendu zatrzymuje kolejne etapy.

## Nowe scenariusze

- Pełne pokrycie zamówienia magazynem: brak zadania produkcji, poprawne rozliczenie wysyłki.
- Brak składników: wycofanie raportu, postępu i wszystkich ruchów magazynowych; po dostawie ponowienie tego samego żądania jest możliwe i nie rozlicza produkcji dwa razy.
- Powtórzenie wysyłki z tym samym kluczem: jedna przesyłka, jeden rozchód.
- Korekta stanu poniżej rezerwacji: odmowa bez zmiany magazynu.
- Anulowany produkt z logo klienta A: nie może zostać przydzielony klientowi B.

## Znany błąd wykrywany przez test

`test_cancelled_custom_label_stock_is_not_allocated_to_another_customer` obecnie NIE przechodzi. Po anulowaniu zamówienia A aplikacja przydziela 5 gotowych opakowań klientowi B na podstawie wspólnego SKU. Oczekiwany przydział to 0, z produkcją nowych opakowań.

Test celowo pozostaje zwykłą asercją: nie jest wyłączony ani oznaczony jako oczekiwane niepowodzenie. Pull request jest roboczy do czasu poprawienia identyfikacji gotowego zapasu. Ten zestaw nie implementuje projektów etykiet.

## Korekta istniejących danych testowych

Test przesyłania grafiki podaje teraz zapisany adres kuriera. Test równoczesnej produkcji jawnie wybiera odbiór osobisty. Zachowano wymaganie adresu w aplikacji.

## Weryfikacja lokalna

37 testów na SQLite: 34 zaliczone, 1 niepowodzenie opisane powyżej, 2 pominięte testy współbieżności wymagające PostgreSQL. Wynik PostgreSQL i kolejnych etapów należy odczytać w GitHub Actions.

## Dodatkowe scenariusze inspirowane projektami open source

Przejrzano rzeczywiste testy, a poniższe scenariusze napisano niezależnie dla API POPMES:
- [ERPNext — rezerwacje](https://github.com/frappe/erpnext/blob/develop/erpnext/stock/doctype/stock_reservation_entry/test_stock_reservation_entry.py): przywrócenie rezerwacji po cofnięciu dostawy, ochrona zapasu innego zamówienia, zwolnienie i ponowna rezerwacja.
- [InvenTree — produkcja](https://github.com/inventree/InvenTree/blob/master/src/backend/InvenTree/build/tests.py): anulowanie zlecenia produkcji.

Dodane testy:
1. Cofnięcie wysyłki przywraca stan i rezerwację; inne zamówienie nie przejmuje tego zapasu.
2. Powtórna korekta z nowym kluczem żądania nie tworzy dodatkowego zapasu ani ruchów.
3. Anulowanie po częściowej wysyłce uwalnia wyłącznie niewysłane opakowania.
4. Anulowanego zamówienia nie można ponownie rozpocząć ani wysłać.
5. Inna gramatura tego samego smaku nie pokrywa zapotrzebowania.
6. Brak drugiego składnika wycofuje również rozchód pierwszego, raport i przyrost gotowych opakowań.

Wszystkie sześć dodatkowych testów przeszło lokalnie. Test izolacji logo nadal wykrywa znany błąd. Testy współbieżności pozostają do wykonania na PostgreSQL w Actions.
