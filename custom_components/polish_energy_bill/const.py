"""Stałe integracji Polski Rachunek za Prąd."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "polish_energy_bill"

PLATFORMS: Final = ["sensor", "number", "button", "select", "date", "datetime"]

# --- klucze config entry (data) ---
CONF_NAME: Final = "name"
CONF_PROFILE: Final = "profile"
CONF_MODE: Final = "mode"                 # "sensor" | "manual"
CONF_ZONE_SENSORS: Final = "zone_sensors" # {zone: entity_id}

# --- klucze options ---
CONF_RATE_OVERRIDES: Final = "rate_overrides"       # {pos_key: float}
CONF_ENABLED_OVERRIDES: Final = "enabled_overrides" # {pos_key: bool}
CONF_BILLING_DAYS: Final = "billing_days"           # int | None (None = auto)
CONF_BILLING_MONTHS: Final = "billing_months"       # float

MODE_SENSOR: Final = "sensor"
MODE_MANUAL: Final = "manual"

# Tryb ustalania zużycia w okresie (wybierany w panelu, encja select):
PERIOD_MODE_ZERO: Final = "punkt_zero"        # bieżący odczyt - punkt zero
PERIOD_MODE_HISTORY: Final = "historia"       # auto z historii licznika (zakres dat)
PERIOD_MODE_READINGS: Final = "reczne_odczyty"  # różnica odczyt końcowy - początkowy
PERIOD_MODE_SINCE: Final = "od_odczytu"        # od daty+godziny odczytu do teraz
PERIOD_MODES: Final = [
    PERIOD_MODE_SINCE,
    PERIOD_MODE_ZERO,
    PERIOD_MODE_HISTORY,
    PERIOD_MODE_READINGS,
]

DEFAULT_BILLING_MONTHS: Final = 1.0

# klucz przechowywania manualnego zużycia per strefa (number encje)
CONF_MANUAL_CONSUMPTION: Final = "manual_consumption"  # {zone: float}

# --- ETS: koszty uprawnień do emisji CO₂ (dobudowana nakładka) -----------
# Dwie metody szacowania; wszystkie parametry edytowalne w UI, bo się zmieniają.
ETS_METHOD_PERCENT: Final = "procent"   # udział % w cenie energii czynnej (komunikat PGE)
ETS_METHOD_EMISSION: Final = "emisja"   # fizyczna: emisja CO₂ × cena EUA × kurs
ETS_METHODS: Final = [ETS_METHOD_PERCENT, ETS_METHOD_EMISSION]

# Wartości STARTOWE edytowalnych pól (nie są zaszyte na stałe — podmieniasz w UI):
DEFAULT_ETS_PERCENT: Final = 55.0          # % udziału w cenie energii (PGE IV kw. 2026)
DEFAULT_ETS_EMISSION_FACTOR: Final = 0.5426  # t CO₂/MWh (PGE „struktura paliw" 2025)
DEFAULT_ETS_EUA_PRICE: Final = 80.0        # EUR/t CO₂ — RYNKOWE, sprawdź i podmień
DEFAULT_ETS_EUR_PLN: Final = 4.30          # PLN/EUR — kurs, podmień

# Prefiks klucza pozycji „energia czynna" — baza metody procentowej.
# Łapie energia_czynna, energia_czynna_dzien, energia_czynna_noc itd.
ETS_ENERGY_KEY_PREFIX: Final = "energia_czynna"
