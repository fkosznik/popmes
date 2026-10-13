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

Hasła ról nie wchodzą do środowiska długo działającej bazy ani backendu. Nowa instalacja z ograniczonymi rolami:

```bash
docker compose up -d database
# dopisz hasła do .env, potem:
bash scripts/postgres-roles.sh
bash scripts/migrate.sh
```

`postgres-roles.sh` przekazuje hasła tylko do jednorazowego `psql`. Istniejący wolumen używa tego samego kroku.

Skrypt nie kasuje danych i nie zmienia nazwy dotychczasowego superusera. `POSTGRES_USER` zostaje kontem administracyjnym bazy. Aplikacja dostaje `POSTGRES_APP_USER` przez `compose.prod.yaml`.

Backend nie dostaje całego pliku `.env`. Dostaje tylko zmienne wypisane w `compose.yaml`. Hasło migracji, repozytorium restic i webhook alertu nie wchodzą do działającego procesu. Produkcja używa `compose.prod.yaml`: `POPMES_ENV=production`, konto `POSTGRES_APP_USER` i brak powrotu do superusera. Migracja jest osobnym poleceniem `bash scripts/migrate.sh`. CI i lokalny development zostają na jednym koncie bazy z `POPMES_ENV=local`.

Kopia i odtworzenie nadal łączą się jako superuser wewnątrz kontenera bazy. To jest potrzebne, żeby `pg_dump` i `pg_restore` widziały cały schemat.

Sprawdzenie SQL ról wykonano na tymczasowej bazie `popmes_rolecheck`, którą potem usunięto. Nie uruchamiano go na danych produkcyjnych.

## Kopie

`bash scripts/backup.sh` zatrzymuje backend, zapisuje spójny zrzut bazy i archiwum grafik, liczy SHA256 i uruchamia backend z powrotem. `backups/LAST_SUCCESS` to czas ostatniej udanej kopii lokalnej i nie zmienia się, gdy kolejna próba padnie. `backups/LOCAL_STATUS` opisuje ostatnią próbę: `running`, `ok`, `dump_failed`, `media_failed`, `checksum_failed` albo `failed`, razem z czasem tej próby. Pliki statusu są podmieniane w całości. Lokalnie skrypt trzyma 14 katalogów (`BACKUP_KEEP`). `BACKUP_RUNNING_MAX_MINUTES` (domyślnie 120) odróżnia trwającą kopię od takiej, która utknęła.

Kopia poza maszynę używa [restic](https://restic.net/). Własnego szyfrowania nie ma. W `.env`:

```dotenv
RESTIC_REPOSITORY=s3:https://example.com/popmes
RESTIC_PASSWORD_FILE=/root/popmes-restic-password
```

Plik hasła restic ma leżeć poza repozytorium restic i poza katalogiem `backups/`. `.env` też kopiuje się osobno, nie jako jedyna kopia razem z zaszyfrowanym zrzutem. Bez `RESTIC_REPOSITORY` skrypt kończy lokalną kopię i zapisuje `OFFSITE_STATUS=not_configured`. Nieudany restic zapisuje status błędu i nie zostawia poprzedniego `ok`. `OFFSITE_SUCCESS` to data ostatniej udanej kopii zewnętrznej. Przy `OFFSITE_REQUIRED=1` monitoring wymaga świeżej kopii zewnętrznej. Zwykły backup wznawia backend przed wysyłką restic. Backup w trakcie `scripts/update.sh` zostawia backend zatrzymany.

Harmonogram jest w `deploy/popmes-backup.cron`. Trzeba go zainstalować na hoście. Nie został zainstalowany na produkcyjnej VM w ramach tej zmiany.

Dwa różne sprawdzenia kopii. Żadne nie rusza wolumenów projektu `popmes`.

`bash scripts/backup-restore-test.sh` odtwarza najnowszą kopię z `--no-owner` i `--no-acl`. To test zawartości. Nie dowodzi, że produkcyjne role i uprawnienia wrócą.

`bash scripts/backup-restore-full.sh` tworzy `popmes_migrate` i `popmes_app`, zapisuje zamówienie, stan i grafikę, robi zrzut, odtwarza go w drugiej izolowanej bazie i uruchamia aplikację na koncie aplikacji. Sprawdza odczyt, zapis, pobranie grafiki oraz odmowę tworzenia tabel, ról i baz.

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

`--verified` sprawdza przez `gh` wyniki `quality` i `application` dla dokładnego SHA. Brak `gh`, oczekujące testy albo błąd kończą aktualizację. Skrypt:

1. Przerywa, gdy drzewo ma lokalne zmiany, brakuje `.env` albo `DEBUG=1`.
2. Blokuje drugą aktualizację plikiem `.update.lock`.
3. Zapisuje obecną i docelową rewizję w `updates/history.log`. Osobno, zanim cokolwiek zbuduje albo zatrzyma, zapisuje identyfikatory obrazów faktycznie używanych przez kontenery w nowym katalogu `updates/<czas>`. Tag `latest` i SHA checkoutu nie są tym identyfikatorem. Brak jednego kontenera albo brak odczytu obrazu kończy aktualizację przed zatrzymaniem usług.
4. Buduje obrazy. Przy błędzie builda z powrotem oznaczane są obrazy zapisane w tym katalogu, nie obraz spod tagu `latest`.
5. Zatrzymuje backend, robi kopię, dopiero potem migracje.
6. Uruchamia kontenery i czeka na healthcheck oraz `/api/health/`.
7. Przy błędzie zostawia bazę bez automatycznego odtworzenia. Powrót to `docker tag` zapisanych identyfikatorów i `docker compose up -d --no-build`. Nie cofa migracji. Ponowna próba dostaje własny katalog i nie nadpisuje poprzedniego zapisu.

Wariant z Caddy: `USE_HTTPS=1` w `.env`. Skrypt dokłada `compose.https.yaml`. `.env`, wolumen bazy i media zostają.

Powrót do poprzednich obrazów nie buduje ich od nowa i nie odtwarza bazy. Odtworzenie bazy jest osobną decyzją i usuwa zapisy zrobione po kopii.

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

Logi kontenerów obracają się przez sterownik `json-file` (10 MB, 5 plików). `scripts/monitor.sh` sprawdza adres aplikacji, zajętość dysku, wiek `LAST_SUCCESS` oraz ostatnią próbę lokalną i zewnętrzną osobno. Adres bierze z `MONITOR_URL`, a gdy go nie ma, z tej samej funkcji co aktualizacja: `HEALTHCHECK_URL`, potem HTTPS z `DOMAIN`, potem HTTP na `APP_PORT`. Nie wyłącza sprawdzania certyfikatu TLS. Nieudana próba lokalna podnosi alarm także wtedy, gdy poprzednia kopia jest świeża. Próba `running` młodsza niż `BACKUP_RUNNING_MAX_MINUTES` alarmu nie podnosi. Przy błędzie i ustawionym `ALERT_WEBHOOK_URL` wysyła krótki tekst, bez haseł i danych klientów. Nie dodano osobnego systemu monitoringu.

## Ochrona gałęzi main

Te ustawienia trzeba włączyć w GitHubie (Settings → Rules → Rulesets, gałąź `main`), jeśli konto nie ma do tego uprawnień z poziomu pull requestu:

- wymagany pull request przed scaleniem,
- wymagane sprawdzenia `quality` i `application`,
- blokada force push i usuwania gałęzi,
- brak pomijania sprawdzeń dla administratorów.

## Grafika po rezerwacji

Nowa wersja etykiety nie zmienia partii już zarezerwowanych albo wyprodukowanych. Zatwierdzenie zapisuje nową grafikę i zostawia wcześniejsze opakowania. Przy zatwierdzaniu operator może jawnie rozliczyć je do magazynu przy ich grafice; historia raportów zostaje. Wysyłka rozchoduje tylko partie zgodne z zatwierdzoną etykietą. Raport dostaje tę etykietę; przy kilku różnych grafikach pole etykiety zostaje puste.

## Przestrzenie robocze

Przestrzeń ogranicza zamówienia, zadania, raporty i grafiki wewnątrz jednej organizacji. To nie jest osobna firma. Szczegóły i ponowienie zapisu z kluczem idempotencji też sprawdzają przestrzeń.

## Logowanie za proxy

Gunicorn ufa `X-Real-IP` tylko wtedy, gdy łączy się z nim prywatny proxy. Nginx na porcie aplikacji nadpisuje ten nagłówek adresem, który sam widzi. Wariant Caddy przekazuje adres klienta, bo do Nginx sięga wtedy wyłącznie Caddy. Limit to 10 prób na konto i 30 na adres w ciągu minuty, liczone atomowo w bazie.

## Przejście istniejącej instalacji

```bash
git fetch origin
bash scripts/update.sh <sha-z-zielonym-CI> --verified
```

SHA musi mieć zaliczone `quality` i `application`. Potem, jeśli włączasz ograniczone role:

```bash
# dopisz POSTGRES_APP_* i POSTGRES_MIGRATE_* do .env
bash scripts/postgres-roles.sh
# ustaw POPMES_ENV=production i USE_HTTPS według VM
bash scripts/update.sh <nowy-sha> --verified
```

Na VM trzeba: włączyć `compose.prod.yaml` przez `POPMES_ENV=production`, uruchomić role, ustawić restic i cron, jeśli mają działać. Samo zielone CI tego nie robi.

## Czego nie sprawdzono na produkcji

- Nie wdrażano tej gałęzi na VM.
- Nie skonfigurowano repozytorium restic i nie wykonano kopii poza VM.
- Nie instalowano crona ani webhooka alertów.
- Nie zmieniano ról na produkcyjnym wolumenie bazy.
