# Historia zmian

## Unreleased

Kolejne zmiany trafiają tutaj, zanim dostaną numer wydania.

## 0.1.3 — 2026-10-29

- Aktualizacja jedną komendą zostawia lokalny `Caddyfile` i nie czeka, gdy test dla tego wydania jest już zielony. Bez tagu pokazuje wydania z GitHuba i proponuje najnowsze.
- Usunięty klient, produkt, wariant i surowiec trafiają do archiwum i można je przywrócić.
- Przycisk Cofnij oraz Ctrl+Z cofają ostatnie przyjęcie towaru albo ostatnie przeniesienie do archiwum.

Aktualizacja istniejącej instalacji, po zielonych kontrolach `quality` i `application` dla tego commita:

```bash
bash scripts/update.sh v0.1.3 --verified
```

## 0.1.2 — 2026-10-29

- Każdy użytkownik ma własny filtr listy zamówień. Wybrany status zostaje po ponownym wejściu w zamówienia.
- Na liście zamówień jest widok „W trakcie realizacji”: wszystkie zamówienia oprócz zrealizowanych.
- W menu Produkcja widać, ile opakowań zostało do wyprodukowania, a w menu Wysyłka, ile zostało do wysłania.
- Z katalogu można usunąć nieużywany smak, wariant, klienta i surowiec. Pozycja użyta w zamówieniu, magazynie albo recepturze zostaje, a komunikat mówi dlaczego.
- Komunikaty błędów podają po polsku, które pole trzeba poprawić.
- Obraz strony podnosi bibliotekę brotli, bo skan obrazu zgłaszał w niej podatność.

Aktualizacja istniejącej instalacji, po zielonych kontrolach `quality` i `application` dla tego commita:

```bash
bash scripts/update.sh v0.1.2 --verified
```

## 0.1.1 — 2026-10-26

- Z otwartego zamówienia, także z przeglądu, można zgłosić produkcję i oznaczyć wysyłkę. Nie trzeba najpierw wchodzić w zakładki Produkcja ani Wysyłka.
- Nowy klient wymaga adresu dostawy. Adres jest rozbity na kod pocztowy, miasto, ulicę i numer domu. Numer lokalu jest opcjonalny. Adresy zapisane wcześniej jedną linijką nadal działają.
- Zgłoszenie produkcji może być mniejsze albo większe niż ilość na zamówieniu. Nadwyżka trafia do magazynu i nie jest zarezerwowana pod to zamówienie.
- Magazyn sortuje się po nazwie, gramaturze, stanie, dostępnej ilości i dostawcy.
- Przyjęcie towaru szuka produktu po nazwie lub kodzie.
- Pillow i pypdf są podniesione do wersji bez zgłoszonych podatności z audytu zależności.

Aktualizacja istniejącej instalacji, po zielonych kontrolach `quality` i `application` dla tego commita:

```bash
bash scripts/update.sh v0.1.1 --verified
```

## 0.1.0 — 2026-10-13

Pierwsze wydanie POPMES. Aplikacja jest na wczesnym etapie: obsługuje codzienną pracę przy zamówieniach, produkcji gotowych opakowań i wysyłce, ale nie jest deklarowana jako w pełni stabilna.

Działa w kodzie tego wydania:

- zamówienie, produkcja gotowych opakowań w sztukach i wysyłka przesyłki do klienta;
- katalog smaków i wariantów, klienci, szkice i zamówienia wielopozycyjne;
- grafika z logo przypisana do partii opakowań, z zatwierdzeniem kolejnej wersji bez zmiany już wyprodukowanych sztuk;
- konta, role, sesja, limit logowania za zaufanym proxy;
- przestrzenie robocze w jednej organizacji;
- kopie lokalne i opcjonalny restic, monitoring oraz aktualizacja wskazanej rewizji albo tagu.

Znane ograniczenia:

- wydanie na GitHubie nie aktualizuje aplikacji na maszynie wirtualnej;
- role PostgreSQL, restic, cron i HTTPS trzeba włączyć osobno na hoście;
- zielone CI nie jest przeglądem bezpieczeństwa produkcji;
- nie ma sklepu, odczytu urządzeń ani automatycznego łączenia zamówień różnych klientów w jedną produkcję.

Instalacja od zera: `python3 scripts/setup.py`, potem `docker compose up -d --build`. Aktualizacja istniejącej instalacji do tego tagu, po zielonych kontrolach `quality` i `application` dla tego commita:

```bash
bash scripts/update.sh v0.1.0 --verified
```

Skrypt przyjmuje tag, bo `git fetch --tags` i `rev-parse` zamieniają go na commit. Nie odtwarza bazy i nie podnosi głównej wersji PostgreSQL.

## Kolejne wydania

Źródłem numeru jest plik `VERSION` w katalogu głównym. `frontend/package.json` ma tę samą wartość; po zmianie `VERSION` uruchom `bash scripts/sync-version.sh`.

- `0.1.4` — poprawki błędów;
- `0.2.0` — kolejny zestaw funkcji;
- zmień `VERSION`, zsynchronizuj package.json, dopisz changelog, uruchom testy, scal zmiany do `main` i poczekaj na zielone kontrole dokładnego commita;
- utwórz tag `vX.Y.Z` wskazujący ten commit i opublikuj GitHub Release;
- raz opublikowanego tagu nie przesuwamy; poprawka dostaje nowy numer.

GitHub Release nie wdraża aplikacji na VM. Na hoście aktualizację robi `bash scripts/update.sh vX.Y.Z --verified`.
