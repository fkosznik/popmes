# POPMES

**Production Operations Platform – Manufacturing Execution System** dla POPME.

Aplikacja webowa po polsku: **zamówienie → produkcja w kg → pakowanie w sztukach → wydanie**. Backend Python/Django + Django REST Framework, interfejs TypeScript/React, PostgreSQL, Docker Compose.

## Uruchomienie

Wymagania: Git, Python 3 (tylko do wygenerowania konfiguracji), Docker Engine/Desktop z Docker Compose v2. Dla opcjonalnego HTTPS: Compose co najmniej 2.24.4.

```bash
git clone https://github.com/fkosznik/popmes.git
cd popmes
python3 scripts/setup.py
docker compose up -d --build
```

Otwórz **http://localhost:8080**. Login: **admin**. Losowe hasło wyświetli skrypt konfiguracji; jest również zapisane w lokalnym `.env`. Przy kolejnych uruchomieniach istniejące hasło nie jest resetowane. `.env` nie trafia do repozytorium.

Pierwszy start wykonuje migracje, tworzy konto administratora i przykładowy katalog POPME: cztery smaki, formaty 30/100/400 g i warianty z logo. **Sprawdź i dostosuj ten katalog do rzeczywistej oferty oraz opakowań.** Automatyczne tworzenie katalogu można wyłączyć przez `SEED_CATALOG=0`.

Opcjonalne przykładowe zamówienia, wyraźnie oznaczone jako DEMO:

```bash
docker compose exec backend python manage.py seed_demo
```

Polecenie nie tworzy dodatkowych kont ani nie nadpisuje istniejących danych. Można je uruchomić ponownie bez powielania demonstracji.

## Pierwsze zamówienie

1. W **Klientach** dodaj odbiorcę (automatycznie aktywny) i jego lokalizacje dostawy.
2. W **Zamówieniach** kliknij **Nowe zamówienie**, wybierz klienta, zapisany adres dostawy, termin, produkty i sztuki. Przy produkcie „z logo” możesz od razu wgrać grafikę. **Zatwierdź do realizacji** rezerwuje wolny zapas FIFO według smaku; produkcja obejmuje tylko brakującą masę.
3. W szczegółach pozycji z logo wgraj PDF, PNG lub JPG i zatwierdź etykietę.
4. W **Produkcji** rozpocznij zadanie. Formularz zgłoszenia podpowie pozostałą masę z planu w kg: możesz ją zmniejszyć dla wykonania częściowego lub wpisać nadwyżkę w osobnym polu. Nadwyżka ponad zapotrzebowanie trafia do wolnego magazynu.
5. W **Pakowaniu** zgłoś sztuki. System pobiera masę z wybranej partii albo najstarszych dostępnych partii tego zamówienia.
6. Po zakończeniu wszystkich pozycji zamówienie ma status **Zrealizowane**. Sprzedaż oznacza **Wydane**.

Każde zgłoszenie oznacza **nową, dodatkową ilość**. Wprowadzanie 50 szt. dwa razy daje 100 szt.; bezpieczne ponowienie tego samego żądania po błędzie połączenia nie tworzy duplikatu.

## Funkcje wersji 0.1

- Konta, wiele ról, kontrola uprawnień po stronie serwera, sesje i CSRF.
- Katalog smaków i wariantów, klienci, archiwizacja, zamówienia wielopozycyjne i szkice.
- Automatyczne zlecenia, sumowanie tego samego smaku w jednym zamówieniu.
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

W ekranie **Zespół** administrator tworzy pracowników, hasła i role:

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

```bash
bash scripts/backup.sh
# Przy aktualizacji: najpierw kopia, potem:
git pull --ff-only
docker compose up -d --build
```

Kopia obejmuje bazę i załączniki z jednego spójnego momentu. Backend jest na krótko zatrzymany; w tym czasie aplikacja nie przyjmuje zapisów. Kopie zapisują się w `backups/`, a katalog docelowy można zmienić przez `BACKUP_DIR`. **Skopiuj kopie oraz `.env` poza host aplikacji.** Skrypt nie konfiguruje automatycznie zewnętrznego magazynu.

Przykład codziennego uruchomienia z crona na hoście (dostosuj ścieżkę i konto z dostępem do Dockera):

```cron
0 2 * * * cd /srv/popmes && bash scripts/backup.sh >> /srv/popmes-backup.log 2>&1
```

Odtwarzanie **zastępuje aktualną bazę i załączniki**. Najpierw sprawdź je na oddzielnym środowisku:

```bash
bash scripts/restore.sh /pelna/sciezka/do/kopii --replace-current-data
```

Przy instalacji HTTPS ustaw `COMPOSE_FILE=compose.yaml:compose.https.yaml` w środowisku, z którego uruchamiasz skrypty. Weryfikuj logi kopii i okresowo wykonuj test odtworzenia. Nie usuwaj wolumenów poleceniem `docker compose down -v` w działającej instalacji.

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

## Aktualizacja: adresy i wspólny magazyn

Widok **Magazyn popcornu** pokazuje per smak wolną masę, masę zarezerwowaną i łączny stan. To magazyn gotowego popcornu luzem (kg), nie osobny magazyn już zapakowanych SKU. Zapas zarezerwowany dla innego zamówienia nie jest dostępny do ponownego przydzielenia. Sam szkic nie rezerwuje stanu. Anulowanie zwalnia pozostałą masę, a zmniejszenie zamówienia uwalnia nadwyżkę.

Migracje 0002/0003 dodają adresy klienta i wolny magazyn. Zachowują historię zamówień, przenoszą istniejący adres klienta na listę lokalizacji i rozdzielają dotychczasową nadwyżkę partii na wolny zapas z zapisami w historii ruchów. Przed aktualizacją wykonaj `bash scripts/backup.sh`, potem `docker compose up -d --build`. Migracja danych 0003 jest nieodwracalna; powrót do poprzedniej wersji wymaga odtworzenia kopii.

Grafika dodana w zamówieniu nadal wymaga zatwierdzenia przed pakowaniem. Adres zapisany w zamówieniu jest kopią wybranej lokalizacji: późniejsza edycja klienta nie zmienia historycznych zamówień.
