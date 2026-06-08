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

## Dokładność

Kalkulator liczy na `Decimal`, zaokrągla każdą pozycję do grosza (`ROUND_HALF_UP`),
a VAT nalicza od sumy netto w danej stawce — zgodnie z polskim sposobem fakturowania.

Na realnej fakturze PGE (G11, okres 31.01–31.03.2026, 667 kWh) kalkulator daje
**668,58 / 822,35 zł** wobec **668,61 / 822,39 zł** z faktury — różnica 3–4 grosze.
Bierze się ona stąd, że PGE zaokrągla **per odczyt** (dwa odczyty w okresie) i liczy
energię z innego zaokrąglenia zużycia niż dystrybucję. Nasz kalkulator jest
wewnętrznie spójny; pojedyncze pozycje miesięczne trafia **co do grosza**.

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

## Osobny panel (dashboard)

W repo jest gotowy widok `dashboards/rachunek_za_prad.yaml` — osobny dashboard,
który dodajesz do **paska bocznego** (jak „Energia"). Pokazuje rachunek prościej
niż faktura: duże „Do zapłaty", podział sprzedaż/dystrybucja, koszt 1 kWh oraz
wykresy kosztów **dzienny / tygodniowy / miesięczny**.

1. **Ustawienia → Dashboardy → Dodaj dashboard → „Nowy dashboard od zera"**;
   nazwa „Rachunek za prąd", ikona `mdi:cash-multiple`, zaznacz *Pokaż w pasku bocznym*.
2. Otwórz go → ⋮ → **Edytuj** → ⋮ → **Edytor surowej konfiguracji** → wklej plik.

Wymaga karty **ApexCharts** (HACS → Frontend → `apexcharts-card`). W pliku są
instrukcje i podmiana `entity_id`, jeśli nazwałeś instancję inaczej niż „Rachunek za prąd".

## Profile w zestawie

| Profil      | Taryfa | Uwagi                                                         |
|-------------|--------|--------------------------------------------------------------|
| `pge_g11`   | G11    | Stawki **1:1 z realnej faktury PGE 2026**.                   |
| `pge_g12`   | G12    | Stawki strefowe **przykładowe** — podmień swoimi.            |
| `pge_g12w`  | G12w   | Jw., taryfa z weekendami w taniej strefie.                   |

## Testy

```bash
pip install -r requirements_test.txt
pytest -q
```

Rdzeń kalkulatora (`core/`) jest niezależny od Home Assistant i w pełni testowalny.

## Licencja

MIT.
