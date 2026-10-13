# Operacje POPMES

Produkcja kończy się gotowymi opakowaniami w sztukach. Pakowanie i wysyłka dotyczą przesyłek dla klientów, a nie osobnego przeliczania kilogramów na sztuki.

Ta instrukcja opisuje pierwszą instalację, role bazy, kopie, aktualizację i odzyskanie. Nie wdraża zmian na produkcyjną maszynę wirtualną.

## Pierwsze uruchomienie

```bash
python3 scripts/setup.py
docker compose up -d --build
```

Pusty wolumen bazy sam wykonuje migracje i tworzy konto administratora. Migracja `0012` dodaje partie grafiki, a `0014` przenosi istniejący niezerowy zapas produktów z logo do partii o nieznanej grafice. Nie zeruje go i nie przypisuje go automatycznie do nowych zamówień. Hasło jest tylko w `.env`. Zwykły restart kontenerów nie uruchamia migracji ponownie.

Lokalny development zostaje po HTTP na `127.0.0.1:8080`. Backend i PostgreSQL nie publikują portów na hoście.

## Role PostgreSQL

Domyślna instalacja nadal używa jednego użytkownika tworzonego przez obraz `postgres` przy pierwszym utworzeniu wolumenu. Zmiana `POSTGRES_USER` w `.env` nie zmienia roli na istniejącym wolumenie.

Docelowo są trzy konta:

| Konto | Po co | Czego nie ma |
|---|---|---|
| `POSTGRES_USER` | Administracja, `pg_dump` i `pg_restore` | Nie jest kontem aplikacji |
| `POSTGRES_MIGRATE_USER` (domyślnie `popmes_migrate`) | Tworzenie i zmiana tabel | Nie jest superuserem i nie tworzy ról ani baz |
| `POSTGRES_APP_USER` (domyślnie `popmes_app`) | Działająca aplikacja: odczyt i zapis wierszy | Nie tworzy tabel, ról ani baz |

Nowa instalacja tworzy role przy pierwszym starcie bazy, jeśli w `.env` są hasła `POSTGRES_APP_PASSWORD` i `POSTGRES_MIGRATE_PASSWORD`. Istniejący wolumen wymaga osobnego kroku:

```bash
# dopisz hasła do .env, potem:
bash scripts/postgres-roles.sh
```

Skrypt nie kasuje danych i nie zmienia nazwy dotychczasowego superusera. Po jego powodzeniu ustaw w `.env` użytkownika aplikacji i zrestartuj backend. Migracje od tej chwili:

```bash
bash scripts/migrate.sh
```

Hasło roli migracji nie jest wpisywane do długo działającego kontenera backendu. CI zostawia użytkownika z prawem tworzenia testowej bazy. To nie jest konfiguracja produkcyjna.

Kopia i odtworzenie nadal łączą się jako superuser wewnątrz kontenera bazy. To jest potrzebne, żeby `pg_dump` i `pg_restore` widziały cały schemat.

Sprawdzenie SQL ról wykonano na tymczasowej bazie `popmes_rolecheck`, którą potem usunięto. Nie uruchamiano go na danych produkcyjnych.

## Kopie

`bash scripts/backup.sh` zatrzymuje backend, zapisuje spójny zrzut bazy i archiwum grafik, liczy SHA256 i uruchamia backend z powrotem. Zostawia `backups/LAST_SUCCESS`. Lokalnie trzyma 14 katalogów (`BACKUP_KEEP`).

Kopia poza maszynę używa [restic](https://restic.net/). Własnego szyfrowania nie ma. W `.env`:

```dotenv
RESTIC_REPOSITORY=s3:https://example.com/popmes
RESTIC_PASSWORD_FILE=/root/popmes-restic-password
```

Plik hasła restic ma leżeć poza repozytorium restic i poza katalogiem `backups/`. `.env` też kopiuje się osobno, nie jako jedyna kopia razem z zaszyfrowanym zrzutem. Bez `RESTIC_REPOSITORY` skrypt kończy lokalną kopię i zapisuje `OFFSITE_STATUS=not_configured`. Nie oznacza to, że kopia poza VM działa.

Harmonogram jest w `deploy/popmes-backup.cron`. Trzeba go zainstalować na hoście. Nie został zainstalowany na produkcyjnej VM w ramach tej zmiany.

Test odtworzenia w osobnym projekcie Compose, bez ruszania wolumenów `popmes`:

```bash
bash scripts/backup-restore-test.sh
```

Odtworzenie na działającą instalację jest ręczne i kasuje bieżące dane:

```bash
bash scripts/restore.sh /pelna/sciezka/do/kopii --replace-current-data
```

Wszystko zapisane po tej kopii przepada.

## Aktualizacja VM

Nie podnosi głównej wersji PostgreSQL. Nie robi automatycznego restore.

```bash
bash scripts/update.sh <tag-albo-commit> --verified
```

`--verified` oznacza, że wymagane sprawdzenia GitHub dla tej rewizji są zielone. Skrypt:

1. Przerywa, gdy drzewo ma lokalne zmiany, brakuje `.env` albo `DEBUG=1`.
2. Blokuje drugą aktualizację plikiem `.update.lock`.
3. Zapisuje obecną i docelową rewizję w `updates/history.log`.
4. Buduje obrazy zanim zatrzyma backend.
5. Zatrzymuje backend, robi kopię, dopiero potem migracje.
6. Uruchamia kontenery i czeka na healthcheck oraz `/api/health/`.
7. Przy błędzie zostawia bazę bez automatycznego odtworzenia i wypisuje komendę powrotu kodu.

Wariant z Caddy: `USE_HTTPS=1` w `.env`. Skrypt dokłada `compose.https.yaml`. `.env`, wolumen bazy i media zostają.

Powrót kodu to `git checkout` poprzedniej rewizji i `docker compose up -d --build`. To nie cofa migracji. Odtworzenie bazy jest osobną decyzją i usuwa zapisy zrobione po kopii.

## HTTPS i logowanie

Przy samym Compose aplikacja jest po HTTP. Przy `compose.https.yaml` Caddy przekierowuje HTTP na HTTPS i ustawia HSTS dla tej jednej domeny, bez `includeSubDomains`.

`manage.py check --deploy` na konfiguracji `DEBUG=0`, `COOKIE_SECURE=1`, `SECURE_HSTS_SECONDS=15552000`, `ALLOWED_HOSTS=popmes.example.com`, `CSRF_TRUSTED_ORIGINS=https://popmes.example.com` zostawia trzy ostrzeżenia:

- **W005** — `SECURE_HSTS_INCLUDE_SUBDOMAINS` jest wyłączone celowo. Włączenie objęłoby wszystkie subdomeny.
- **W008** — backend nie wymusza przekierowania na HTTPS. Słucha tylko w sieci Dockera, a healthcheck jest po HTTP. Publiczne przekierowanie robi Caddy.
- **W021** — brak HSTS preload. Aplikacja nie jest zgłaszana do listy preload przeglądarek.

Ciasteczko sesji jest `Secure` (gdy `COOKIE_SECURE=1`), `HttpOnly` i `SameSite=Lax`. Ciasteczko CSRF jest czytelne dla JavaScript, bo interfejs wysyła je jako `X-CSRFToken`. To nie jest usterka.

Limit logowania to 10 prób na minutę na adres klienta, liczonych w tabeli `LoginAttempt`. Wspólna baza oznacza, że limit obowiązuje wszystkie procesy Gunicorn.

## Porządki techniczne

```bash
docker compose exec -T backend python manage.py purge_technical
```

Usuwa wygasłe sesje, liczniki logowania starsze niż jeden dzień i klucze idempotencji starsze niż 7 dni. Przez 7 dni ten sam `Idempotency-Key` może bezpiecznie powtórzyć żądanie. Wcześniejsze skasowanie klucza pozwoliłoby wykonać operację drugi raz. Polecenie nie usuwa zamówień, ruchów magazynowych, raportów ani korekt.

## Monitoring

Logi kontenerów obracają się przez sterownik `json-file` (10 MB, 5 plików). `scripts/monitor.sh` sprawdza `/api/health/`, zajętość dysku i wiek `LAST_SUCCESS`. Przy błędzie i ustawionym `ALERT_WEBHOOK_URL` wysyła krótki tekst, bez haseł i danych klientów. Nie dodano osobnego systemu monitoringu.

## Ochrona gałęzi main

Te ustawienia trzeba włączyć w GitHubie (Settings → Rules → Rulesets, gałąź `main`), jeśli konto nie ma do tego uprawnień z poziomu pull requestu:

- wymagany pull request przed scaleniem,
- wymagane sprawdzenia `quality` i `application`,
- blokada force push i usuwania gałęzi,
- brak pomijania sprawdzeń dla administratorów.

## Czego nie sprawdzono na produkcji

- Nie wdrażano tej gałęzi na VM.
- Nie skonfigurowano repozytorium restic i nie wykonano kopii poza VM.
- Nie instalowano crona ani webhooka alertów.
- Nie zmieniano ról na produkcyjnym wolumenie bazy.
