# Polski Rachunek za Prąd — integracja Home Assistant

Liczy **w miarę dokładny** polski rachunek za energię elektryczną w Home Assistant.
Polska faktura ma kilkanaście pozycji (energia czynna, opłata OZE, kogeneracyjna,
dystrybucyjna sieciowa/jakościowa, stała, abonament, opłata mocowa, akcyza…), a
stawki zmieniają się częściej niż pogoda. Dlatego **każda pozycja i każda stawka
jest osobną, edytowalną encją** — podmieniasz w UI, rachunek przelicza się od ręki.

## Co dostajesz

- Sensory: **do zapłaty (brutto)**, należność netto, VAT, zużycie w rachunku.
- Sumy per grupa: **sprzedaż**, **dystrybucja**, **podatki**.
- Osobny sensor (diagnostyczny) dla **każdej pozycji** — z ilością, stawką, VAT i brutto w atrybutach.
- Encje `number` „Stawka: …" do **podmieniania każdej stawki** bez restartu i bez edycji plików.
- Profile taryf w YAML (PGE G11/G12/G12w) + nadpisywanie stawek w UI (hybryda).
- Dwa tryby zużycia: **z sensora HA** (np. licznik / `utility_meter`) albo **ręczne** wpisywanie kWh.
- **Punkt zero**: pierwszy odczyt licznika ustawiasz jako „zero" (przyciskiem lub ręcznie), a koszty liczą się od niego.
- **Osobny panel** w pasku bocznym z dużymi, czytelnymi kwotami i **wykresami kosztów dzień/tydzień/miesiąc** (ApexCharts) — prościej niż na fakturze.
- **Szacunek ETS (CO₂)** — ile z rachunku to koszty uprawnień do emisji. Osobne encje i wykres, **nie zmieniają** reszty rachunku (czysta nakładka).

## Dokładność

Kalkulator liczy na `Decimal`, zaokrągla każdą pozycję do grosza (`ROUND_HALF_UP`),
a VAT nalicza od sumy netto w danej stawce — zgodnie z polskim sposobem fakturowania.

Na realnej fakturze PGE (G11, okres 31.01–31.03.2026, 667 kWh) kalkulator daje
**668,58 / 822,35 zł** wobec **668,61 / 822,39 zł** z faktury — różnica 3–4 grosze.
Bierze się ona stąd, że PGE zaokrągla **per odczyt** (dwa odczyty w okresie) i liczy
energię z innego zaokrąglenia zużycia niż dystrybucję. Nasz kalkulator jest
wewnętrznie spójny; pojedyncze pozycje miesięczne trafia **co do grosza**.

Na fakturze z **pojedynczym odczytem** (nr 408000059008, G11, 634 kWh, okres
21.05–20.07.2026) kalkulator trafia **co do grosza na całości**: 639,10 / 146,99 /
**786,09 zł** — dokładnie jak faktura (test `test_real_invoice_408000059008_exact`).

Zużycie PGE rozlicza w **pełnych kWh** (dane z OSD): 4709,5→5343,0 = 633,5 → **634**,
5343,0→6136,3 = 793,3 → **793**. W trybie *Ręczne odczyty* dodatek zaokrągla różnicę
odczytów tak samo (połówki w górę), dzięki czemu faktura nr 470000065575 (G11,
21.07–20.09.2026, 793 kWh) wychodzi **co do grosza**: 781,19 / 179,67 / **960,86 zł**
(test `test_invoice_470000065575_exact`). Tryby bieżące (*Z faktury*, *Od odczytu do
teraz*) liczą zużycie wprost z licznika, bez zaokrąglenia — to prognoza narastająca.

Opłaty stałe PGE nalicza za **pełne miesiące kalendarzowe** (na tej fakturze
01.06–31.07 = 2 mc), a okres odczytu energii bywa inny (21.05–20.07). Dodatek to
odwzorowuje: dla **zamkniętego zakresu dat** zaokrągla miesiące opłat stałych do
pełnych, więc rachunek trafia co do grosza z samych dat. W trybie bieżącym
(*od odczytu do teraz*) opłaty stałe liczą się proporcjonalnie (narastają z
czasem). Możesz też wymusić liczbę miesięcy ręcznie (encja *Opłaty stałe: liczba
miesięcy*, 0 = auto).

## Instalacja (HACS)

1. HACS → Integrations → menu (⋮) → **Custom repositories**.
2. Dodaj URL tego repo, kategoria **Integration**.
3. Zainstaluj „Polski Rachunek za Prąd", zrestartuj Home Assistant.
4. Ustawienia → Urządzenia i usługi → **Dodaj integrację** → „Polski Rachunek za Prąd".

Instalacja ręczna: skopiuj `custom_components/polish_energy_bill/` do swojego
katalogu `config/custom_components/` i zrestartuj HA.

## Konfiguracja

**Krok 1.** Wybierz profil taryfowy (np. *PGE Obrót — G11*) i źródło zużycia
(sensor HA / ręczne).

**Krok 2(sensor).** Wskaż sensor zużycia `[kWh]` — dla taryf wielostrefowych osobny
sensor na strefę dzienną i nocną (np. dwa `utility_meter` z taryfami HA).

**Opcje** (przycisk *Konfiguruj*): liczba miesięcy/dni okresu rozliczeniowego oraz
które pozycje są aktywne.

## Podstawianie stawek

Sednem integracji są encje `number` o nazwie **„Stawka: …"** — po jednej na pozycję.
Gdy URE albo sprzedawca zmieni stawkę, wpisujesz nową wartość w UI i tyle. Wartości
są pamiętane między restartami. Domyślne stawki podmienisz też trwale w plikach
profili: `custom_components/polish_energy_bill/core/profiles_data/*.yaml`.

### Dodanie własnego profilu

Skopiuj `pge_g11.yaml`, zmień `key`, `name`, `tariff` i listę `positions`.
Każda pozycja:

```yaml
- key: energia_czynna          # stabilny identyfikator
  name: za energię czynną      # nazwa jak na fakturze
  group: sale                  # sale | distribution | tax | other
  unit: per_kwh                # per_kwh | per_mwh | per_month | per_day | flat
  zone: all                    # all | day | night | peak | off_peak
  rate: "0.50320"              # cena NETTO
  vat: "0.23"                  # stawka VAT (ułamek)
  enabled: true                # opcjonalne
```

## Punkt zero (od czego liczymy)

W trybie sensorowym licznik pokazuje stan narastająco (np. 4877 kWh). Rachunek ma
liczyć od początku okresu, więc ustalasz **punkt zero**:

- przycisk **„Ustaw jako zero"** — zapisuje bieżący odczyt sensora jako start okresu, albo
- pole **„Odczyt zero"** — wpisujesz wartość ręcznie (np. odczyt z faktury).

Zużycie = bieżący odczyt − punkt zero (nigdy ujemne). Na początku nowego okresu
naciskasz „Ustaw jako zero" i koszty startują od nowa. W trybie ręcznym po prostu
wpisujesz zużycie w kWh.

## Zakres dat i tryby okresu

W panelu wybierasz **okres rozliczeniowy datami „od–do"** oraz **tryb** liczenia
zużycia (encja select „Tryb zużycia okresu"):

- **Z faktury (domyślny, najprostszy)** — wpisujesz dwie rzeczy z ostatniej
  faktury: **datę końcowego odczytu** i **końcowe wskazanie licznika**. Dodatek
  pokazuje narastający rachunek bieżącego okresu: zużycie = bieżący licznik −
  wskazanie (dokładnie, z realnego licznika), a opłaty stałe liczą się
  proporcjonalnie do czasu od tej daty. Na kolejnej fakturze zmieniasz tylko te
  dwa pola. Karta „Nowy okres z faktury" na górze panelu robi to w dwóch polach.
- **Od odczytu do teraz** — wpisujesz **datę i godzinę odczytu** z faktury (encja
  „Punkt zero — data i godzina odczytu"). Integracja liczy zużycie i koszt od tej
  chwili do teraz, z historii licznika. To bieżący, narastający rachunek od
  ostatniego odczytu — i automatycznie aktualizuje się w czasie.
- **Auto z historii** — podajesz zakres dat „od–do", a integracja pobiera zużycie z
  historii licznika (long-term statistics z recordera) za ten zamknięty okres.
  Wymaga, by licznik miał statystyki sięgające wstecz.
- **Ręczne odczyty** — wpisujesz odczyt początkowy i końcowy; zużycie = różnica.
- **Punkt zero** — bieżący odczyt minus punkt zero (jak wyżej).

Z dat liczona jest też liczba dni i miesięcy okresu (do opłat stałych) — okres
kalendarzowy, więc np. 31.01→31.03 to dokładnie 2 miesiące (opłaty stałe ×2),
zgodnie z fakturą. Wybrany zakres pojawia się w nagłówku tabeli „jak na fakturze".

## ETS — udział kosztów CO₂ w rachunku

Koszt uprawnień do emisji CO₂ (ETS) **nie jest osobną pozycją** polskiej faktury —
jest zaszyty w cenie energii czynnej. Integracja szacuje go jako **nakładkę** na
gotowy rachunek (nic w nim nie zmienia) i daje wybór jednej z dwóch metod (encja
select **„ETS: metoda liczenia"**):

- **Udział % w cenie energii** — PGE publikuje go kwartalnie w komunikacie
  (§37 ust. 2 rozporządzenia taryfowego): **55 % w IV kw. 2026** (56 % w 2025).
  Liczone wprost: `ETS = udział × wartość energii czynnej`. Najbliżej faktury.
- **Emisja CO₂ × cena EUA × kurs** — fizyczne: `zużycie[MWh] × wskaźnik[t/MWh] ×
  cena_EUA[EUR/t] × EUR/PLN`. Wskaźnik **0,5426 t/MWh** ze „struktury paliw" PGE 2025.

Wszystkie parametry **zmieniają się w czasie**, więc są **edytowalnymi polami**
(encje `number`), pamiętanymi między restartami — nie ma stałych w kodzie:
udział %, wskaźnik emisji, cena uprawnienia EUA `[EUR/t]`, kurs EUR/PLN.

Encje wynikowe: **koszt ETS (brutto)**, **udział w rachunku [%]**, **emisja CO₂ [kg]**
oraz **stawka ETS [zł/kWh]** (mnożnik na wykresie kosztu w czasie). W atrybutach
sensora kosztu jest komplet: obie metody, udziały i emisja. Na panelu dochodzi
kafelki, donut **ETS vs reszta** i wykres **kosztu ETS dziennie**.

> Ceny EUA i kurs są rynkowe — wpisz aktualne wartości. Domyślne (80 EUR/t,
> 4,30 PLN/EUR) to tylko punkt startowy.

## Opłaty stałe i opłata mocowa (segmenty)

**Opłaty stałe — pełne miesiące.** Polskie opłaty stałe (mocowa, składnik stały
sieciowej, abonament) są naliczane za pełne miesiące kalendarzowe. Przy
zamkniętym zakresie dat dodatek zaokrągla miesiące do pełnych (21.05→20.07 = 2),
więc odwzorowuje fakturę co do grosza. Tryb bieżący liczy proporcjonalnie.
Encja *Opłaty stałe: liczba miesięcy* (0 = auto) pozwala wymusić wartość.

**Opłata mocowa — auto-segment.** Dla gospodarstw domowych opłata mocowa jest
ryczałtowa i zależy od **rocznego zużycia** w punkcie poboru (progi
500 / 1200 / 2800 kWh → 4 segmenty). Encja select *Opłata mocowa: tryb*:

- **Ręcznie** (domyślnie) — jedna stawka, jak dotąd (encja „Stawka: opłata mocowa").
- **Auto wg zużycia rocznego** — podajesz roczne zużycie (faktura: „zużycie w
  roku poprzednim"), a dodatek wybiera stawkę właściwego segmentu.

Stawki segmentów to osobne, edytowalne pola (zmieniają się co roku). Domyślne
wartości to **stawki URE na 2026** (Informacja Prezesa URE nr 58/2025 z 30.10.2025,
netto zł/mc):

| Segment | Roczne zużycie | Stawka 2026 |
|--------:|:---------------|------------:|
| seg.1 | ≤ 500 kWh | 4,29 |
| seg.2 | 500–1200 kWh | 10,31 |
| seg.3 | 1200–2800 kWh | 17,18 |
| seg.4 | > 2800 kWh | 24,05 |

Gdy URE ogłosi stawki na kolejny rok — podmień pola segmentów. (Dla porównania:
faktura 408000059008 ma „Opłata mocowa seg.4" = 24,05, bo roczne zużycie > 2800 kWh.)

## Osobny panel (dashboard)

Dodatek sam tworzy osobny dashboard w pasku bocznym (jak „Energia"). Pokazuje
rachunek prościej niż faktura: duże „Do zapłaty", podział sprzedaż/dystrybucja,
koszt 1 kWh oraz wykresy kosztów **dzienny / tygodniowy / miesięczny**.

**Instalacja jednym kliknięciem:** urządzenie integracji → przycisk **„Zainstaluj
dashboard"** (albo usługa `polish_energy_bill.install_dashboard`). Dostajesz
zwykły, **edytowalny** dashboard `rachunek-za-prad` — to jednorazowa kopia, dodatek
nie zmienia jej sam z siebie, więc Twoje przeróbki są bezpieczne.

- `entity_id` są brane z rejestru encji Twojej instalacji (nie zależą od nazwy
  urządzenia). Karty, wiersze i serie wskazujące encje, których nie ma (np. wykresy
  z licznika w trybie ręcznym), są pomijane zamiast zostawiać puste kafelki.
- Istniejącego dashboardu przycisk **nie** nadpisuje. Żeby podmienić go na świeży
  (Twoje ręczne zmiany w nim przepadną): usługa z `overwrite: true`; inny adres/tytuł:
  pola `url_path`, `title`; kilka wpisów integracji: `config_entry_id`.
- Po instalacji pojawia się powiadomienie z linkiem i listą ewentualnych braków
  (m.in. brak zasobu `apexcharts-card`).
- Gdy przyszła wersja HA zmieni wewnętrzne API Lovelace, dodatek niczego nie psuje:
  zapisuje gotowy YAML do `polish_energy_bill_dashboard.yaml` w katalogu konfiguracji
  i opisuje w powiadomieniu, jak go wkleić.

Wymaga karty **ApexCharts** (Katalog społeczności / HACS → Frontend → `apexcharts-card`).

**Ręcznie** (np. bez przycisku): plik `dashboards/rachunek_za_prad.yaml` wklejasz w
**Ustawienia → Dashboardy → Dodaj dashboard → „Nowy dashboard od zera"** → ⋮ → **Edytuj** →
⋮ → **Edytor surowej konfiguracji**. Jest w nim komplet `entity_id` z instalacji autora
(`rachunek_za_prad_…` / `liczniki_rachunek_za_prad_…`) — przy innych nazwach użyj przycisku.
(Kopia szablonu w pakiecie `custom_components/polish_energy_bill/dashboard_template.yaml`
musi być identyczna — pilnuje tego test.)

## Profile w zestawie

| Profil      | Taryfa | Uwagi                                                         |
|-------------|--------|--------------------------------------------------------------|
| `pge_g11`   | G11    | Stawki **1:1 z realnej faktury PGE 2026**.                   |
| `pge_g12`   | G12    | Stawki strefowe **przykładowe** — podmień swoimi.            |
| `pge_g12w`  | G12w   | Jw., taryfa z weekendami w taniej strefie.                   |
| `tauron_g12w`  | G12w   | TAURON Sprzedaż — taryfa G12w (rok 2026).                   |

## Testy

```bash
pip install -r requirements_test.txt
pytest -q                                   # rdzeń + generator dashboardu (bez HA)

pip install -r requirements_test_ha.txt     # opcjonalnie: testy warstwy HA
pytest -q                                   # + tests/ha (prawdziwy rdzeń HA)
```

Rdzeń kalkulatora (`core/`) jest niezależny od Home Assistant i w pełni testowalny.
Testy w `tests/ha` (instalacja dashboardu, przycisk, usługa) uruchamiają prawdziwy
Home Assistant z `pytest-homeassistant-custom-component` — bez tej paczki są pomijane.
Zostały przepuszczone na HA 2026.2.3; na nowszych wersjach wewnętrzne API Lovelace
może się zmienić (wtedy te testy pierwsze to pokażą).

## Licencja

MIT.
