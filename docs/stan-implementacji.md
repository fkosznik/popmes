# Stan wersji 0.1

Wersja jest przygotowana do uruchomienia i przeglądu procesu POPME. Specyfikacja pozostaje punktem odniesienia; poniżej jawnie opisano uproszczenia pierwszej implementacji.

## Działający zakres

Logowanie i role, katalog/klienci/zespół, szkice, automatyczne zlecenia, częściowa produkcja, częściowe pakowanie, FIFO lub wskazana partia, wersje i zatwierdzanie etykiet, chronione pliki, start/pauza, wstrzymanie, anulowanie, wydanie, korekty, produkcja uzupełniająca, transfer/rozchód partii, historia oraz uruchamianie przez Docker Compose.

## Uproszczenia i kolejne iteracje

- Formularz zatwierdzonego zamówienia zmienia ilości istniejących pozycji, termin, priorytet i uwagi. Dodanie nowego smaku po rozpoczęciu pracy obsługujemy na razie oddzielnym zamówieniem; rozbudowa struktury takiego zamówienia wymaga dalszego formularza i rozliczenia historii.
- Szkic z już wgranymi etykietami nie pozwala przebudować pozycji; można go zatwierdzić i zmienić ilości z historią. Najwygodniej dodawać pliki po ustaleniu listy pozycji.
- Powiązanie zapotrzebowania wynika z zamówienia i produktu. Nie ma jeszcze osobnej tabeli przydziałów wielu zamówień do jednej produkcji.
- Korekta cofa cały raport, po czym można dopisać poprawny. Częściowa korekta jednego raportu wymaga osobnego rozbudowania mechanizmu.
- Transfer przenosi całą dostępną pozostałość partii. Rozdzielenie pozostałości między kilka zamówień wymaga rozszerzenia modelu przydziałów. Kilka partii w jednym raporcie jest obsługiwane przez FIFO i API; ręczny formularz wybiera jedną partię albo FIFO.
- Etykiety można pobierać; podgląd PDF/obrazu w aplikacji i wskazywanie dowolnej innej grafiki niż etykieta są rozszerzeniami.
- Kopie mają skrypty oraz instrukcję crona i odtworzenia. Zewnętrzny cel kopii i harmonogram trzeba skonfigurować na rzeczywistym serwerze.
- Pulpit pokazuje postęp, terminy, braki i blokady. Rozbudowane raporty wydajności, historia wykresów, plan obciążenia i optymalizacja są etapem kolejnym.
- Brak pełnego trybu offline: aplikacja sygnalizuje problem i zachowuje otwarty formularz. Odświeżenie/zamknięcie strony usuwa niezapisany formularz.
- Snapshot obejmuje całą historię zamówień. Dla większej instalacji należy dodać paginację, filtry serwerowe i optymalizację zapytań.
- Limit logowania DRF jest podstawowy i liczony lokalnie w procesie. Publiczne wdrożenie warto uzupełnić o wspólny limiter reverse proxy lub cache.

Receptury/BOM, partie surowców, magazyn materiałów, zestawy, planowanie wsadów, integracje Shoper/InvenTree/MQTT oraz fizyczna waga/czujnik nie należą do tej implementacji i nie są przedstawiane jako gotowe funkcje.

## Weryfikacja

Testy backendu pokrywają przepływ częściowy, grupowanie smaku, zamrożenie gramatury, idempotencję, etykiety, deficyt po stratach, korekty, transfery, anulowanie i blokady, role oraz CSRF. Oddzielny test PostgreSQL uruchamia dwóch pracowników próbujących równocześnie zużyć tę samą masę.

Test Playwright przechodzi w interfejsie: logowanie → klient → zamówienie → dwie porcje produkcji i pakowania → zrealizowanie → wydanie. Sprawdza również szerokość widoku mobilnego.

Workflow GitHub Actions buduje cały zestaw Docker, wykonuje testy PostgreSQL, test przeglądarkowy i porównanie danych po backup/restore. Wynik uruchomienia należy sprawdzić w zakładce Actions; obecność pliku workflow nie jest sama w sobie dowodem przejścia tych testów.
