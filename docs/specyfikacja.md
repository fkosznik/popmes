# POPMES — specyfikacja funkcjonalna pierwszej wersji

Wersja dokumentu: 0.1  
Data: 7 października 2026  
Status: propozycja do przeglądu przed implementacją  
Projekt: Production Operations Platform – Manufacturing Execution System  
Zastosowanie: obsługa zamówień, produkcji i pakowania w POPME.

Dokument opisuje docelowe zachowanie pierwszej wersji. Zapisanie go w repozytorium nie oznacza, że wymienione funkcje zostały już zaimplementowane. Szczegółowe rozwiązania poniżej są propozycjami projektowymi wynikającymi z uzgodnionego obiegu.

## 1. Cel i granice pierwszej wersji

Sprzedawca wybiera produkty z katalogu i przyjmuje zamówienie. Po zatwierdzeniu praca automatycznie pojawia się na ekranie produkcji. Pracownik zgłasza gotowy popcorn, który staje się dostępny dla pakowania. Pakowanie raportuje sztuki, a system automatycznie rozpoznaje zakończenie zamówienia.

Pierwsza wersja obejmuje:

- logowanie, konta i role;
- klientów, produkty produkcyjne i warianty sprzedażowe;
- zamówienia z wieloma pozycjami, terminem, uwagami i etykietami;
- automatyczne utworzenie zleceń produkcji i pakowania;
- raportowanie częściowego wykonania;
- podstawowe identyfikatory partii gotowego popcornu;
- przypisanie wykorzystanej masy do pakowania;
- blokady, korekty, historię działań i panel postępu;
- uruchamianie przez Docker Compose oraz kopie bazy i załączników.

Receptury/BOM, magazyn surowców, automatyczne grupowanie wielu zamówień, zestawy produktów, integracja ze sklepem, urządzeniami i optymalizacja harmonogramu są kolejnymi etapami. Pierwsza wersja zawiera jednak ewidencję dostępnej masy gotowego popcornu, konieczną do poprawnej obsługi pakowania.

## 2. Podstawowe pojęcia i jednostki

| Pojęcie | Znaczenie |
|---|---|
| Produkt produkcyjny | Popcorn określonego smaku i specyfikacji; rozliczany masowo |
| Wariant sprzedażowy | Produkt produkcyjny + gramatura + opakowanie + sposób etykietowania |
| Zamówienie | Wymagania klienta: pozycje, ilości, termin i personalizacja |
| Zlecenie produkcji | Zadanie przygotowania określonej masy produktu |
| Partia | Identyfikowalna porcja produktu powstała podczas produkcji |
| Zlecenie pakowania | Zadanie zapakowania konkretnej pozycji zamówienia |
| Raport | Zapis wykonania, zużycia lub korekty wraz z autorem i czasem |

Produkcja pracuje w g lub kg, a pakowanie w całkowitych sztukach. Dane masowe zapisujemy jako liczby dziesiętne o ustalonej precyzji w gramach; nie używamy zmiennoprzecinkowych przybliżeń do rozliczania ilości.

Zapotrzebowanie netto = liczba sztuk × masa netto opakowania.

Przykład: 200 × 30 g = 6000 g = 6 kg. Pierwsza wersja nie dolicza automatycznie strat ani nie zaokrągla zapotrzebowania do pełnych wsadów. Kierownik może zwiększyć cel produkcyjny z podaniem przyczyny. Rzeczywisty uzysk jest raportowany niezależnie od celu.

## 3. Role i uprawnienia

Jedno konto może mieć kilka ról. Wszelkie uprawnienia są sprawdzane również przez backend.

| Rola | Dostęp |
|---|---|
| Sprzedaż | Klienci, tworzenie i zatwierdzanie zamówień, etykiety, postęp, oznaczenie wydania |
| Produkcja | Kolejka produkcji, instrukcje, rozpoczęcie, pauza, raportowanie masy i problemów |
| Pakowanie | Kolejka pakowania, etykiety, rozpoczęcie, pauza, raportowanie sztuk i zużycia |
| Kierownik | Wszystkie zamówienia, kolejność, blokady, korekty, anulowanie, zmiana planu, raporty |
| Administrator | Konta, role, katalog i konfiguracja; uprawnienia operacyjne przez dodatkowe role |

Produkcja nie potrzebuje danych kontaktowych klienta ani cen. Pakowanie widzi nazwę klienta, numer zamówienia oraz instrukcje potrzebne do wykonania zadania. Ceny nie są wymagane w pierwszej wersji.

## 4. Katalog i klienci

### Produkt produkcyjny

Pola: kod, nazwa, jednostka prezentacji g/kg, instrukcja produkcji, aktywność. Opcjonalnie orientacyjny uzysk jednego wsadu, używany początkowo tylko informacyjnie.

### Wariant sprzedażowy

Pola: kod/SKU, nazwa, produkt produkcyjny, masa netto większa od zera, typ opakowania, sposób etykietowania (standardowe/personalizowane), instrukcja pakowania, aktywność.

Grafika klienta należy do pozycji zamówienia. Nie tworzymy osobnego SKU dla każdego klienta. Zmiana katalogu nie zmienia danych już zatwierdzonego zamówienia.

### Klient

Nazwa jest obowiązkowa. Osoba kontaktowa, telefon, e-mail, NIP i adres są opcjonalne w podstawowym obiegu. Przy dostawie kurierskiej wymagany jest adres dostawy. Dane klienta kopiujemy do zamówienia, aby późniejsza zmiana kontaktu nie zmieniała historii.

Archiwizacja produktu lub klienta wyłącza wybór w nowych zamówieniach, ale zachowuje wcześniejsze powiązania.

## 5. Ekrany aplikacji

| Ekran | Zawartość | Najważniejsze działania |
|---|---|---|
| Logowanie | Login, hasło, informacja o błędzie | Zaloguj, wyloguj |
| Pulpit | Liczba aktywnych i opóźnionych zamówień, zadania dzisiejsze, blokady | Otwórz zamówienie lub kolejkę |
| Zamówienia | Numer, klient, termin, status, postęp produkcji i pakowania | Nowe zamówienie, wyszukaj, filtruj |
| Formularz zamówienia | Klient, termin, pozycje, uwagi, pliki | Zapisz szkic, zatwierdź do realizacji |
| Szczegóły zamówienia | Pozycje, ilości, etykiety, zlecenia i historia | Edytuj według uprawnień, wstrzymaj, wznów, anuluj, oznacz wydanie |
| Produkcja | Zakładki Do wykonania / W trakcie / Wykonane, widoczne blokady | Rozpocznij, pauza, zgłoś wykonanie, zgłoś problem |
| Pakowanie | Oczekujące / Gotowe / W trakcie / Zakończone | Rozpocznij, pauza, zgłoś pakowanie, pobierz etykietę |
| Katalog i klienci | Listy i formularze | Dodaj, edytuj, archiwizuj |
| Administracja | Użytkownicy i konfiguracja | Nadaj role, dezaktywuj konto |

Ekrany produkcji i pakowania są dostosowane do tabletów: duże przyciski, krótkie formularze, wyraźne ilości. Domyślne sortowanie: pilne, następnie najbliższy termin, następnie numer zamówienia. Filtry obejmują smak, termin, status i numer.

## 6. Formularz zamówienia

| Pole | Wymaganie |
|---|---|
| Klient | Obowiązkowy przy zatwierdzaniu; wybór lub szybkie dodanie |
| Termin gotowości | Obowiązkowy; data i godzina lokalna |
| Priorytet | Standardowy lub pilny; domyślnie standardowy |
| Pozycje | Co najmniej jedna; wariant z katalogu i dodatnia całkowita liczba sztuk |
| Uwagi produkcyjne | Opcjonalne, widoczne na produkcji |
| Uwagi pakowania | Opcjonalne; wspólne i dla danej pozycji |
| Uwagi wewnętrzne | Widoczne dla sprzedaży i kierownika |
| Odbiór | Kurier (domyślnie) / paczkomat / odbiór osobisty / inny |
| Etykieta | Plik i status osobno dla pozycji wymagającej personalizacji |
| Adres dostawy | Wymagany dla kuriera i paczkomatu |

Numer, np. ZAM-2026-00001, nadaje system i nie używa go ponownie. Szkic może być niekompletny.

Przy zatwierdzeniu system atomowo:

1. Sprawdza wymagane pola i aktywność produktów.
2. Utrwala nazwy, gramatury, opakowania i instrukcje jako dane zamówienia.
3. Tworzy zapotrzebowanie masowe.
4. Tworzy zlecenie produkcji dla każdego produktu produkcyjnego w tym zamówieniu.
5. Tworzy osobne zlecenie pakowania dla każdej pozycji.
6. Zapisuje autora i moment zatwierdzenia.

Jeśli ten sam smak występuje w dwóch gramaturach, produkcja w obrębie zamówienia otrzymuje sumę mas. Zamówienia różnych klientów mają w pierwszej wersji odrębne zlecenia. Ponowienie żądania zatwierdzenia nie tworzy duplikatów.

## 7. Statusy i postęp

### Zamówienie

| Status | Warunek |
|---|---|
| Szkic | Jeszcze niezatwierdzone |
| Do realizacji | Zatwierdzone, bez rozpoczętej pracy |
| W realizacji | Rozpoczęto pracę, pozostały sztuki do zapakowania |
| Zrealizowane | Wszystkie pozycje osiągnęły wymagane liczby dobrych sztuk |
| Wydane | Całe zrealizowane zamówienie przekazano klientowi lub przewoźnikowi |
| Anulowane | Kierownik zakończył realizację z podaniem przyczyny |

Wstrzymanie jest osobną blokadą z przyczyną, autorem i czasem. Nie usuwa statusu ani dotychczasowego postępu. Lista wyświetla np. „Wstrzymane — w realizacji”. Wznowienie usuwa blokadę; aktualny status wynika z danych.

Postęp pokazujemy osobno: wyprodukowana masa / cel, zapakowane sztuki / zamówione sztuki. Status zamówienia wynika z raportów; gotowa produkcja nie oznacza jeszcze zrealizowanego zamówienia.

### Zadania

Produkcja: Do wykonania → W trakcie → Wykonane. Rozpoczęcie i pauza służą rejestracji pracy. Zadanie po pauzie pozostaje rozpoczęte, ale ma zatrzymany licznik aktywnego czasu.

Pakowanie: Oczekujące → Gotowe → W trakcie → Zakończone. Gotowość oznacza możliwość zapakowania co najmniej jednej sztuki, a nie dostępność całej zamówionej ilości. Rozpoczęte zadanie może czekać na kolejną porcję; nadal pokazuje postęp i przyczynę oczekiwania.

Zablokowane zadania są widoczne, lecz nie pozwalają rozpocząć pracy ani zapisać nowego wykonania. Zakończenie zadania produkcyjnego następuje po osiągnięciu celu; niedobór pozostaje otwarty do uzupełnienia lub decyzji kierownika.

## 8. Ekran i raport produkcji

Karta zadania pokazuje numer, smak, masę docelową, zgłoszoną i pozostałą, termin, priorytet, instrukcję oraz powiązane pozycje zamówienia.

Po „Zgłoś wykonanie” pracownik podaje:

- masę nowego dobrego produktu, gotowego do pakowania;
- opcjonalną masę odpadu, osobno od dobrego produktu;
- oznaczenie partii: nowa partia lub kolejna porcja istniejącej partii tego zlecenia;
- opcjonalny komentarz.

System proponuje nowy numer partii, np. PART-20261007-001. Każdy raport dotyczy dodatkowej ilości, a formularz wyraźnie pokazuje dotychczasową sumę.

Zapis dodaje masę do dostępności i aktualizuje kolejkę pakowania. Zgłoszenie produkcji oznacza, że popcorn jest gotowy do przekazania, np. po wymaganym suszeniu i studzeniu.

Pracownik może zgłosić więcej niż cel — system wyróżnia nadwyżkę. Nadwyżka pozostaje rozliczona przy partii i nie zwiększa automatycznie liczby zamówionych opakowań.

## 9. Ekran i raport pakowania

Karta pokazuje klienta, numer i pozycję zamówienia, smak, gramaturę, opakowanie, wymaganą liczbę sztuk, postęp, dostępne partie, etykietę i instrukcję.

Warunki rozpoczęcia: brak blokady, dostępna masa na co najmniej jedną sztukę i zatwierdzona wymagana etykieta. Dostępność samych opakowań sprawdza pracownik; w pierwszej wersji ich stanów magazynowych nie ewidencjonujemy. Brak opakowań zgłasza jako problem.

Raport zawiera:

- dodatkową liczbę dobrych zapakowanych sztuk;
- partie i masę pobraną z każdej z nich;
- opcjonalne straty i komentarz.

Domyślne zużycie = liczba sztuk × gramatura. Jest oznaczone jako szacowane. Pracownik może podać rzeczywiste zużycie, uwzględniające naddatek i straty; system zapisuje sposób ustalenia masy. Strata jest częścią całkowitego zużycia, a nie drugim odjęciem.

System blokuje zużycie większe od dostępności, ujemne ilości oraz przekroczenie pozostałej liczby zamówionych sztuk. Suma pobrań z partii musi odpowiadać zużyciu raportu. Rzeczywiste zużycie nie może być mniejsze od deklarowanej masy netto dobrych sztuk; odstępstwo wymaga wyjaśnienia i korekty danych przez kierownika.

Raport zapisuje liczbę sztuk, wykorzystane partie i wersję etykiety. Kilka partii w jednym raporcie oznacza, że wszystkie dotyczą tego fragmentu pakowania; dokładne rozdzielenie sztuk między partie wymaga osobnych raportów.

## 10. Dostępność, niedobory i nadwyżki

Podstawowy bilans partii:

Dostępne = dobra masa przyjęta − zużycie pakowania − pozostałe rozchody + korekty.

W pierwszej wersji masa jest przypisana do źródłowego zamówienia. Pozycje tego samego smaku korzystają ze wspólnej puli tego zamówienia. Widoczne dostępności nie są niezależnymi rezerwacjami dla każdej pozycji; zapis raportu zawsze ponownie sprawdza wspólny bilans.

Dla rozpoczętego zamówienia system oblicza:

- pozostałe netto do pakowania = suma (niezapakowane sztuki × gramatura);
- aktualny deficyt = max(0, pozostałe netto − dostępna masa).

Deficyt po stratach pakowania pojawia się na pulpicie. Kierownik przyciskiem „Dodaj produkcję uzupełniającą” tworzy dodatkowe zlecenie, uwzględniając już zaplanowaną, niewykonaną produkcję. Ponowienie tej samej czynności nie może tworzyć podwójnego uzupełnienia.

Nadwyżka po ukończeniu lub anulowaniu zamówienia trafia do listy „Do decyzji”. Kierownik może przypisać dostępny zgodny produkt do innego zamówienia albo zarejestrować rozchód z przyczyną. Każdy transfer zachowuje pochodzenie partii. Jest to podstawowe rozliczanie produktu, a nie pełny magazyn surowców.

## 11. Etykiety i załączniki

Obsługiwane początkowo formaty: PDF, PNG i JPG, maksymalnie 20 MB na plik. Serwer sprawdza rzeczywisty typ pliku. Dostęp do plików wymaga uprawnień do zamówienia.

Dla personalizowanej pozycji status etykiety to Brak / Do zatwierdzenia / Zatwierdzona. Sprzedaż lub kierownik zapisuje zatwierdzenie z autorem i czasem. Brak etykiety nie blokuje produkcji popcornu, ale blokuje pakowanie danej pozycji.

Każde przesłanie tworzy wersję. Zastąpienie zatwierdzonej etykiety cofa gotowość pozostałego pakowania do ponownego zatwierdzenia. Wcześniejsze raporty zachowują odwołanie do użytej wersji. System wskazuje już zapakowaną liczbę sztuk do oceny kierownika.

Przy etykiecie standardowej używana jest zatwierdzona wersja przypisana do wariantu lub utrwalona instrukcja etykietowania; wybór jest widoczny na karcie.

## 12. Zmiany, anulowanie i poprawki

- Szkic: sprzedaż może swobodnie edytować i usuwać.
- Zatwierdzone bez rozpoczętej pracy: sprzedaż może zmienić dane przez ponowne zatwierdzenie; system pokazuje różnice i aktualizuje zadania w jednej transakcji.
- Po rozpoczęciu pracy: ilości, terminy i instrukcje zmienia kierownik, z przyczyną i podglądem wpływu na pozostałą pracę.
- Nie wolno zmniejszyć zamówionej liczby poniżej liczby dobrych zapakowanych sztuk bez wcześniejszej korekty. Zmiana gramatury lub smaku po rozpoczęciu wymaga nowej pozycji i rozliczenia starej.
- Anulowanie wymaga przyczyny, zatrzymuje niewykonaną pracę i zachowuje wszystkie raporty oraz produkt. Nie udaje, że wyprodukowany towar przestał istnieć.
- Błędny raport koryguje kierownik przez zapis powiązanej korekty. Oryginał pozostaje w historii. Nie wolno skorygować wyprodukowanej masy poniżej już zużytej bez rozliczenia zależnych raportów.
- Ponowne pakowanie wymaga rozliczenia wycofanych dobrych sztuk i losu produktu; cofnięcie sztuk nie przywraca automatycznie masy popcornu.
- Korekta zmniejszająca postęp może ponownie otworzyć zamówienie zrealizowane. Zamówienia wydanego nie otwieramy automatycznie; kierownik wykonuje jawne cofnięcie wydania z przyczyną.

## 13. Historia, czas i niezawodność

Historia zawiera obiekt, działanie, autora, czas, przyczynę oraz zmianę wartości. Zatwierdzonych raportów nie usuwamy fizycznie.

Czas przechowujemy z jednoznaczną strefą, a interfejs wyświetla Europe/Warsaw. Raporty rozróżniają czas kalendarzowy od aktywnego czasu pracy. Pauza zatrzymuje aktywny czas; zamknięcie karty przeglądarki samo w sobie nie stanowi potwierdzenia zakończenia pracy.

Po zapisie backend zatwierdza zmianę, a pozostałe ekrany aktualizują kolejkę automatycznie; cel pierwszej wersji: do 5 sekund przy sprawnym połączeniu. Sposób realizacji wybierzemy w projekcie technicznym.

Przy utracie połączenia interfejs pokazuje brak synchronizacji. Formularz pozostaje dostępny do ponowienia, lecz wykonanie nie jest oznaczone jako zapisane przed potwierdzeniem serwera. Żądania zapisu mają identyfikator zapobiegający powieleniu.

Transakcje i kontrola współbieżności chronią przed dwukrotnym zużyciem partii oraz utratą zmian przy równoczesnej pracy. Nieaktualny formularz dostaje czytelny komunikat i aktualne dane.

## 14. Minimalny model danych

| Obiekt | Najważniejsze dane i relacje |
|---|---|
| Użytkownik, rola | Konta, wiele ról, aktywność |
| Klient | Dane identyfikacyjne i kontaktowe |
| Produkt produkcyjny | Smak/specyfikacja i instrukcja |
| Wariant sprzedażowy | Produkt, gramatura, opakowanie, etykietowanie |
| Zamówienie | Numer, klient, termin, priorytet, status, blokada, wersja zmian |
| Pozycja zamówienia | Wariant, utrwalone parametry, ilość, instrukcje |
| Zlecenie produkcji | Produkt, cel masowy, status i źródło zapotrzebowania |
| Powiązanie zapotrzebowania | Zlecenie produkcji ↔ pozycja zamówienia, wymagana masa |
| Partia | Numer, produkt, pochodzenie, data, dostępność wynikająca z zapisów |
| Raport produkcji | Partia, dobra masa, odpady, wykonawca i czas |
| Zlecenie pakowania | Pozycja, ilość docelowa i status |
| Raport pakowania i pobrania | Sztuki, partie, masy, sposób pomiaru, wersja etykiety |
| Sesja pracy | Użytkownik, zadanie, start, pauza/koniec |
| Ruch produktu i korekta | Przyjęcie, zużycie, transfer, rozchód, odniesienie do źródła |
| Załącznik i wersja etykiety | Plik, pozycja, wersja i zatwierdzenie |
| Zdarzenie i blokada | Historia, przyczyna i odpowiedzialna osoba |

Partia może zasilać wiele raportów pakowania, a raport może korzystać z wielu partii. Model powiązań zapotrzebowania ma pozwolić w przyszłości na produkcję dla wielu zamówień, choć interfejs pierwszej wersji tego automatycznie nie grupuje.

## 15. Architektura i uruchomienie

Pierwsza implementacja: frontend, modułowy backend i relacyjna baza danych, uruchamiane przez Docker Compose. Proxy obsługuje HTTPS przy wdrożeniu. Worker jest rozszerzeniem, gdy pojawią się zadania w tle.

Backend odpowiada za reguły biznesowe, uprawnienia, transakcje i API. Frontend prezentuje dane i formularze. Baza oraz załączniki mają trwałe wolumeny. Baza nie jest udostępniana publicznie.

Repozytorium zawiera instrukcję uruchomienia, przykład konfiguracji bez sekretów i migracje bazy. Nie zawiera katalogu, receptur, stanów magazynowych ani zamówień. Sekrety oraz dane z bazy nie trafiają do Git.

Przed pilotażem: automatyczna codzienna kopia bazy i załączników, kopia poza hostem aplikacji oraz przeprowadzony test odtworzenia. Konkretne biblioteki, wersje i schemat API wybierzemy w kolejnym kroku.

## 16. Przykład pełnego obiegu

Zamówienie przykładowe, bez nazw z oferty:

- 200 × smak A 30 g z etykietą klienta = 6 kg;
- 50 × smak B 100 g = 5 kg.

Po zatwierdzeniu powstają dwa zlecenia produkcji i dwa pakowania.

1. Produkcja zgłasza 4 kg smaku A.
2. Po zatwierdzeniu etykiety pakowanie zgłasza 100 szt. po 30 g i 3 kg zużycia.
3. Pozostaje 1 kg smaku A oraz 100 szt. do zapakowania. Zadanie produkcji nadal wymaga 2 kg.
4. Produkcja zgłasza kolejne 2 kg; dostępne stają się 3 kg.
5. Pakowanie wykonuje pozostałe 100 szt., zużywając 3 kg z dostępnych partii.
6. Smak B przechodzi analogiczny proces: 5 kg i 50 szt.
7. Zamówienie staje się zrealizowane dopiero po zakończeniu obu pozycji.
8. Sprzedaż oznacza wydanie. Historia zachowuje wykonawców, ilości i powiązania partii.

W przykładzie zużycie odpowiada nominalnej masie i nie ma strat. Jeżeli zużycie jest większe, system wykazuje rzeczywisty deficyt.

## 17. Kryteria odbioru pierwszej wersji

| ID | Scenariusz | Oczekiwany wynik |
|---|---|---|
| A01 | Zatwierdzenie wielopozycyjnego zamówienia | Powstają właściwe zlecenia i sumy mas |
| A02 | Ten sam smak w kilku gramaturach | Wspólna produkcja w zamówieniu, osobne pakowania |
| A03 | Podwójne kliknięcie zatwierdzenia lub ponowienie raportu | Brak podwójnych zleceń i ilości |
| A04 | Częściowa produkcja | Dostępna część może zostać zapakowana, brak pozostaje widoczny |
| A05 | Niekompletne zamówienie | Nie otrzymuje statusu zrealizowane |
| A06 | Brak zatwierdzonej etykiety | Produkcja działa, pakowanie danej pozycji czeka |
| A07 | Dwie osoby zużywają tę samą dostępną masę | Zapis nie prowadzi do ujemnego bilansu |
| A08 | Straty podczas pakowania | Masa rozliczona raz, deficyt widoczny, uzupełnienie nie dubluje planu |
| A09 | Anulowanie po częściowym wykonaniu | Zachowane raporty i fizyczny produkt, pozostała praca zatrzymana |
| A10 | Zmiana katalogowej gramatury | Zatwierdzone zamówienia zachowują pierwotne parametry |
| A11 | Korekta raportu | Historia pozostaje kompletna, statusy i bilanse są ponownie obliczone |
| A12 | Utrata sieci po kliknięciu zapisu | Brak fałszywego potwierdzenia i bezpieczne ponowienie |
| A13 | Próba czynności spoza roli przez API | Odmowa po stronie backendu |
| A14 | Pakowanie z dwóch partii | Można odtworzyć powiązania między raportem, partiami i zamówieniem |
| A15 | Wymiana etykiety po częściowym pakowaniu | Stara wersja pozostaje przy wykonaniu, nowa wymaga zatwierdzenia |
| A16 | Kopia i odtworzenie | Zamówienia, raporty i załączniki są dostępne po odtworzeniu |

To scenariusze do wykorzystania podczas implementacji i pilotażu, nie informacja o już wykonanych testach.

## 18. Kolejność implementacji i praca dyplomowa

1. Projekt techniczny: wybór stosu, struktura repozytorium, model danych i kontrakt API.
2. Środowisko Docker Compose, migracje, logowanie i role.
3. Katalog, klienci, formularz zamówienia i automatyczne zlecenia.
4. Raportowanie produkcji, partie i bilans produktu.
5. Pakowanie, etykiety, częściowe wykonanie i status zamówienia.
6. Korekty, blokady, historia, kopie i testy scenariuszy odbioru.
7. Pilotaż na rzeczywistych zamówieniach POPME i poprawki użyteczności.
8. Rozszerzenia: planowanie wsadów i łączenie zamówień, BOM/magazyn, integracja sprzętowa i raporty.

Dla pracy „Projektowanie systemu zarządzania produkcją w fabryce zgodnie z koncepcją Przemysłu 4.0” dokumentujemy cyfrowy przepływ danych, identyfikowalność produktu, współpracę stanowisk i architekturę integracji. Zakres dyplomowy warto rozszerzyć o rzeczywisty odczyt z wagi lub czujnika oraz ocenę na zebranych danych. Zakres akceptuje promotor.

Pierwsza wersja śledzi partie produktu gotowego; pełne powiązanie z partiami surowców wymaga późniejszego modułu materiałowego. Nie deklarujemy pełnej identyfikowalności surowców przed jego wdrożeniem.

Do pomiaru efektów: czas od zatwierdzenia do zakończenia, terminowość, czas oczekiwania między produkcją i pakowaniem oraz liczba korekt. Definicje wskaźników i sposób zbierania danych ustalamy przed pilotażem; poprawy wyników nie zakładamy z góry.
