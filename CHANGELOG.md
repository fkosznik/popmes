# Historia zmian

## Unreleased

Kolejne zmiany trafiają tutaj, zanim dostaną numer wydania.

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

- `0.1.1` — poprawki błędów;
- `0.2.0` — kolejny zestaw funkcji;
- zmień `VERSION`, zsynchronizuj package.json, dopisz changelog, uruchom testy, scal zmiany do `main` i poczekaj na zielone kontrole dokładnego commita;
- utwórz tag `vX.Y.Z` wskazujący ten commit i opublikuj GitHub Release;
- raz opublikowanego tagu nie przesuwamy; poprawka dostaje nowy numer.

GitHub Release nie wdraża aplikacji na VM. Na hoście aktualizację robi `bash scripts/update.sh vX.Y.Z --verified`.
