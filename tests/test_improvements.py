"""Testy dwóch usprawnień:
1) opłaty stałe za pełne miesiące kalendarzowe (BillingPeriod.from_dates),
2) auto-wybór segmentu opłaty mocowej (core.power_fee).

Uruchom: pytest -q
"""

from datetime import date
from decimal import Decimal as D

import pytest

from core import (
    BillingPeriod,
    Consumption,
    Zone,
    calculate,
    load_builtin_profiles,
    power_fee_rate_for,
    power_fee_segment_for,
    SEGMENT_THRESHOLDS,
)


# --------------------------------------------------------------------------
# Usprawnienie 1: pełne miesiące kalendarzowe dla opłat stałych
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "start, end, expected_whole",
    [
        (date(2026, 5, 21), date(2026, 7, 20), D("2")),   # faktura 408 → 2 mc
        (date(2026, 1, 31), date(2026, 3, 31), D("2")),   # 2,0 → 2
        (date(2026, 6, 1), date(2026, 6, 30), D("1")),    # ~1 mc → 1
        (date(2026, 1, 1), date(2026, 1, 10), D("1")),    # krótki → min 1
        (date(2026, 1, 1), date(2026, 12, 31), D("12")),  # ~rok → 12
    ],
)
def test_from_dates_whole_months(start, end, expected_whole):
    assert BillingPeriod.from_dates(start, end, whole_months=True).months == expected_whole


def test_from_dates_default_is_fractional():
    """Domyślnie (whole_months=False) zachowanie bez zmian — ułamek."""
    bp = BillingPeriod.from_dates(date(2026, 5, 21), date(2026, 7, 20))
    assert bp.months < D("2")  # ~1,97 — jak dotąd


def test_408_invoice_exact_via_whole_month_dates():
    """Faktura 408000059008 odtworzona CO DO GROSZA z samych DAT.

    Zakres 21.05→20.07 + whole_months=True → opłaty stałe za 2 pełne mc,
    więc suma = 786,09 bez ręcznego ustawiania liczby miesięcy.
    """
    g11 = load_builtin_profiles()["pge_g11"]
    bp = BillingPeriod.from_dates(date(2026, 5, 21), date(2026, 7, 20), whole_months=True)
    bill = calculate(g11, Consumption({Zone.ALL: D("634")}), bp)
    assert bill.line("oplata_mocowa_stala").net == D("48.10")   # 2 × 24,05
    assert bill.line("oplata_stala_dystr").net == D("19.96")    # 2 × 9,98
    assert bill.line("abonament_dystr").net == D("4.50")        # 2 × 2,25
    assert bill.net == D("639.10")
    assert bill.gross == D("786.09")


# --------------------------------------------------------------------------
# Usprawnienie 2: auto-wybór segmentu opłaty mocowej
# --------------------------------------------------------------------------

def test_segment_thresholds():
    assert SEGMENT_THRESHOLDS == (500, 1200, 2800)


@pytest.mark.parametrize(
    "annual, seg",
    [
        (0, 1), (500, 1),            # granica 500 w seg.1
        (500.5, 2), (1200, 2),       # do 1200 w seg.2
        (1200.5, 3), (2800, 3),      # do 2800 w seg.3
        (2800.5, 4), (3632, 4),      # powyżej 2800 w seg.4 (nasze zużycie)
    ],
)
def test_segment_for(annual, seg):
    assert power_fee_segment_for(annual) == seg


def test_rate_for_uses_2026_rates():
    """Stawki URE 2026 (Informacja 58/2025): 4,29 / 10,31 / 17,18 / 24,05."""
    rates = ("4.29", "10.31", "17.18", "24.05")
    assert power_fee_rate_for(300, rates) == D("4.29")     # seg.1
    assert power_fee_rate_for(800, rates) == D("10.31")    # seg.2
    assert power_fee_rate_for(2000, rates) == D("17.18")   # seg.3
    assert power_fee_rate_for(3632, rates) == D("24.05")   # seg.4 (faktura)


def test_auto_power_fee_matches_invoice():
    """Auto-segment dla zużycia 3632 kWh/rok daje seg.4 = 24,05 (jak na fakturze)."""
    g11 = load_builtin_profiles()["pge_g11"]
    rate = power_fee_rate_for(3632, ("4.29", "10.31", "17.18", "24.05"))
    prof = g11.customize(rate_overrides={"oplata_mocowa_stala": rate})
    bill = calculate(prof, Consumption({Zone.ALL: D("634")}), BillingPeriod(months=D("2")))
    assert bill.line("oplata_mocowa_stala").net == D("48.10")  # 2 × 24,05
