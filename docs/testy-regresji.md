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

31 testów na SQLite: 28 zaliczonych, 1 niepowodzenie opisane powyżej, 2 pominięte testy współbieżności wymagające PostgreSQL. Wynik PostgreSQL i kolejnych etapów należy odczytać w GitHub Actions.
