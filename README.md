# POPMES

**Production Operations Platform – Manufacturing Execution System** dla POPME.

Aplikacja webowa po polsku: **zamówienie → produkcja gotowych opakowań w sztukach → wysyłka przesyłki do klienta**. Backend Python/Django + Django REST Framework, interfejs TypeScript/React, PostgreSQL, Docker Compose.

## Uruchomienie

Wymagania: Git, Python 3 (tylko do wygenerowania konfiguracji), Docker Engine/Desktop z Docker Compose v2. Dla opcjonalnego HTTPS: Compose co najmniej 2.24.4.

```bash
git clone https://github.com/fkosznik/popmes.git
cd popmes
python3 scripts/setup.py
docker compose up -d --build
```

Otwórz **http://localhost:8080**. Login: **admin**. Losowe hasło wyświetli skrypt konfiguracji; jest również zapisane w lokalnym `.env`. Przy kolejnych uruchomieniach istniejące hasło nie jest resetowane. `.env` nie trafia do repozytorium.

Pierwszy start pustej bazy wykonuje migracje, tworzy konto administratora i przykładowy katalog POPME: cztery smaki, formaty 30/100/400 g i warianty z logo. **Sprawdź i dostosuj ten katalog do rzeczywistej oferty oraz opakowań.** Automatyczne tworzenie katalogu można wyłączyć przez `SEED_CATALOG=0`. Zwykły restart kontenera nie uruchamia migracji ponownie. Na istniejącej bazie migracje robi `bash scripts/migrate.sh` albo `bash scripts/update.sh`.

Opcjonalne przykładowe zamówienia, wyraźnie oznaczone jako DEMO:

```bash
docker compose exec backend python manage.py seed_demo
```

Polecenie nie tworzy dodatkowych kont ani nie nadpisuje istniejących danych. Można je uruchomić ponownie bez powielania demonstracji.

## Pierwsze zamówienie

1. W **Klientach** dodaj odbiorcę (automatycznie aktywny) i jego lokalizacje dostawy.
2. W **Zamówieniach** kliknij **Nowe zamówienie**, wybierz klienta, zapisany adres dostawy, termin, produkty i sztuki. Przy produkcie „z logo” możesz od razu wgrać grafikę. **Zatwierdź do realizacji** tworzy zlecenie produkcji na każde opakowanie. Przy kurierze powstaje też zlecenie przesyłki.
3. W szczegółach pozycji z logo wgraj PDF, PNG lub JPG i zatwierdź etykietę.
4. W **Produkcji** rozpocznij zadanie i zgłoś gotowe opakowania w sztukach. Możesz zgłaszać częściami. Grafika z logo musi być zatwierdzona, zanim powstaną opakowania. Gotowe opakowania z logo zostają przy tym projekcie i tej wersji etykiety; nie wracają do wspólnego zapasu innego klienta.
5. W **Pakowaniu** oznacz przesyłkę dla klienta. Bez gotowych opakowań przesyłki nie da się utworzyć.
6. Po zakończeniu wszystkich pozycji zamówienie ma status **Zrealizowane**. Sprzedaż oznacza **Wydane**.

Każde zgłoszenie oznacza **nową, dodatkową ilość**. Wprowadzanie 50 szt. dwa razy daje 100 szt.; bezpieczne ponowienie tego samego żądania po błędzie połączenia nie tworzy duplikatu.

## Funkcje wersji 0.1

- Konta, wiele ról, kontrola uprawnień po stronie serwera, sesje i CSRF.
- Katalog smaków i wariantów, klienci, archiwizacja, zamówienia wielopozycyjne i szkice.
- Automatyczne zlecenia: produkcja liczona w opakowaniach, pakowanie jako przesyłka do kuriera.
- Kolejki produkcji i pakowania, pilne terminy, filtry, częściowe wykonanie.
- Start/pauza czasu pracy, problemy i blokady, wznowienie i anulowanie.
- Partie, bilans masy, wybór partii lub FIFO, rzeczywiste albo szacowane zużycie, straty.
- Etykiety z wersjami i zatwierdzeniem, chronione pobieranie, historia wersji użytej do pakowania.
- Korekta pełnego raportu z pozostawieniem oryginału; jawna decyzja o przywróceniu masy.
- Edycja ilości i terminów, ochrona przed zapisem nieaktualnego formularza.
- Zlecenia uzupełniające, transfer pozostałości partii i rozchód z przyczyną.
- Historia, panel postępu, odświeżanie co 5 sekund, widok na tablet i telefon.
- Trwałe wolumeny, skrypty kopii/odtworzenia, opcjonalne HTTPS przez Caddy.

Receptury/BOM, pełny magazyn surowców, optymalizacja harmonogramu, połączenie zamówień różnych klientów w jedną produkcję, zestawy, sklep i odczyty urządzeń są kolejnymi modułami zgodnie ze specyfikacją. Szczegóły zakresu i ograniczenia: [stan implementacji](docs/stan-implementacji.md).

## Konta i role

W ekranie **Administracja** administrator tworzy pracowników, hasła i role:

| Rola | Dostęp |
|---|---|
| Sprzedaż | Klienci, zamówienia, etykiety i wydanie |
| Produkcja | Produkcja, raporty masy i zgłaszanie problemów |
| Pakowanie | Pakowanie, etykiety i raporty sztuk |
| Kierownik | Operacje, korekty, blokady, zapas i plan |
| Administrator | Katalog i użytkownicy; dla pracy operacyjnej dodaj pozostałe role |

Początkowy superadministrator ma pełny dostęp. Zwykłe konto „Administrator” nie otrzymuje automatycznie uprawnień operacyjnych. Produkcja nie otrzymuje danych kontaktowych klientów z API.

## Sieć lokalna i HTTPS

Domyślnie port jest dostępny tylko na komputerze uruchamiającym Dockera. Aby udostępnić aplikację w sieci zakładu, w `.env` ustaw np.:

```dotenv
BIND_IP=0.0.0.0
ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50
CSRF_TRUSTED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://192.168.1.50:8080
```

Podstaw własny adres hosta i wykonaj `docker compose up -d`. Dla dostępu przez domenę ustaw DNS, `DOMAIN`, `ALLOWED_HOSTS` (zachowaj `127.0.0.1` dla healthcheck), `CSRF_TRUSTED_ORIGINS=https://twoja-domena` i `COOKIE_SECURE=1`, następnie:

```bash
docker compose -f compose.yaml -f compose.https.yaml up -d --build
```

Caddy pobiera certyfikat; porty 80/443 muszą być dostępne dla tej domeny. Baza i backend nie mają portów publikowanych na hoście. Przy własnym reverse proxy zachowaj nagłówki Host i X-Forwarded-Proto. Nie udostępniaj bezpośrednio portu backendu.

## Kopie i aktualizacje

Szczegóły ról bazy, restic, aktualizacji konkretnej rewizji i odzyskania: [operacje](docs/operacje.md).

```bash
bash scripts/backup.sh
bash scripts/update.sh <tag-albo-commit> --verified
```

Kopia obejmuje bazę i grafiki z jednego momentu. Backend jest na krótko zatrzymany. Lokalny katalog to `backups/` albo `BACKUP_DIR`. Wysyłka poza VM działa dopiero po ustawieniu repozytorium restic i udanej próbie. Harmonogram jest w `deploy/popmes-backup.cron` i trzeba go zainstalować na hoście.

Odtwarzanie na tę samą instalację **zastępuje** bazę i grafiki. Zapisy zrobione po kopii przepadają. Najpierw sprawdź kopię osobno:

```bash
bash scripts/backup-restore-test.sh
bash scripts/backup-restore-full.sh
bash scripts/restore.sh /pelna/sciezka/do/kopii --replace-current-data
```

`backup-restore-test.sh` sprawdza tylko zawartość (`--no-owner --no-acl`). Pełne role sprawdza `backup-restore-full.sh`. Żaden z nich nie kasuje wolumenów działającej instalacji.

Nie usuwaj wolumenów poleceniem `docker compose down -v` w działającej instalacji. Nie podnoś w ten sposób głównej wersji PostgreSQL.

## Testy i rozwój

```bash
docker compose exec backend python manage.py test core -v 2
docker compose exec backend python manage.py makemigrations --check --dry-run
cd frontend
npm ci
npm run build
npx playwright install chromium
POP_TEST_URL=http://127.0.0.1:8080 POP_TEST_USER=admin POP_TEST_PASSWORD='haslo-konta-testowego' npx playwright test
```

Test przeglądarkowy zapisuje klienta i zamówienie E2E — uruchamiaj go w oddzielnej instalacji testowej. GitHub Actions buduje kontenery, uruchamia testy na PostgreSQL, przechodzi obieg w przeglądarce i porównuje dane po odtworzeniu kopii.

Lokalny rozwój bez Dockera: Python 3.12, `pip install -r backend/requirements.txt`, ustaw `DJANGO_SECRET_KEY`, `DB_ENGINE=sqlite`, `ADMIN_PASSWORD` oraz `CSRF_TRUSTED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173`. Uruchom migracje, bootstrap i seed_catalog, potem `python backend/manage.py runserver` oraz `npm run dev --prefix frontend`. SQLite służy tylko do prostych testów lokalnych — test blokad współbieżności wymaga PostgreSQL.

## Dokumentacja

- [Specyfikacja funkcjonalna](docs/specyfikacja.md)
- [Architektura i API](docs/architektura.md)
- [Stan implementacji i dalszy rozwój](docs/stan-implementacji.md)
- [Operacje: role bazy, kopie, aktualizacja](docs/operacje.md)

## Aktualizacja: opakowania i przesyłki

Produkcja kończy się gotowymi opakowaniami w sztukach. Wolny stan standardowego produktu schodzi na zamówienie, a produkcja dostaje tylko brakującą liczbę. Opakowania z logo są osobną partią wariantu, projektu graficznego i wersji etykiety. Karta **Magazyn** pozwala dodawać kategorie, produkty i przyjęcia towaru. Katalog produktów pokazuje wspólny stan wariantu, bez cudzych grafik. Receptura wariantu zużywa surowce przy zgłoszeniu produkcji. Surowiec może mieć dostawcę. Kliknięcie pozycji pokazuje szczegóły oraz edycję nazwy i dostawcy. Zakładka **Wysyłka** pokazuje całe zamówienie z adresem i kontaktem. Przycisk **Wysłano** oznacza całą przesyłkę.

Migracja 0004 dopisuje liczbę wyprodukowanych opakowań i tabelę przesyłek. Dla starszych pozycji przyjmuje, że już zapakowane sztuki są wyprodukowanymi opakowaniami. Nie kasuje zamówień ani plików. Przed aktualizacją wykonaj `bash scripts/backup.sh`, potem `docker compose up -d --build`.

Grafika pozycji z logo musi być zatwierdzona przed zgłoszeniem opakowań. Adres zapisany w zamówieniu jest kopią wybranej lokalizacji.
