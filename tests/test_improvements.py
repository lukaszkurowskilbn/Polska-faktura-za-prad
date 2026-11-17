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
    DEFAULT_SEGMENT_RATES_2026,
    consumption_from_readings,
    round_kwh,
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


# --------------------------------------------------------------------------
# Tryb „Z faktury": zużycie = licznik − wskazanie, opłaty stałe proporcjonalnie
# --------------------------------------------------------------------------

def test_invoice_mode_math():
    """Zużycie z różnicy licznik−wskazanie + okres proporcjonalny do czasu.

    To kontrakt trybu „Z faktury": consumption = bieżący licznik − końcowe
    wskazanie z FV; okres (opłaty stałe) = from_dates(data odczytu, teraz),
    ułamek miesięcy (narastająco). Dla dokładnie 2,0 mc daje 2 × opłaty stałe.
    """
    from datetime import date as _date

    g11 = load_builtin_profiles()["pge_g11"]
    bp = BillingPeriod.from_dates(_date(2026, 1, 31), _date(2026, 3, 31))  # 2,0 mc
    assert bp.months == D("2")
    meter_now, reading = D("5977"), D("5343")       # 634 kWh
    bill = calculate(g11, Consumption({Zone.ALL: meter_now - reading}), bp)
    assert bill.consumption_kwh == D("634")
    assert bill.line("oplata_mocowa_stala").net == D("48.10")   # 2 × 24,05
    assert bill.gross == D("786.09")


def test_invoice_mode_fixed_fees_scale_with_time():
    """Im dłużej od odczytu, tym większe opłaty stałe (proporcjonalnie)."""
    from datetime import date as _date

    g11 = load_builtin_profiles()["pge_g11"]
    cons = Consumption({Zone.ALL: D("100")})
    b1 = calculate(g11, cons, BillingPeriod.from_dates(_date(2026, 1, 1), _date(2026, 2, 1)))
    b2 = calculate(g11, cons, BillingPeriod.from_dates(_date(2026, 1, 1), _date(2026, 3, 1)))
    assert b2.line("oplata_mocowa_stala").net > b1.line("oplata_mocowa_stala").net
    # Zużycie (część zmienna) takie samo — zależy od licznika, nie od czasu.
    assert b1.line("energia_czynna").net == b2.line("energia_czynna").net


# --------------------------------------------------------------------------
# Zużycie z odczytów — pełne kWh jak na fakturze PGE
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [("633.5", "634"), ("793.3", "793"), ("0.5", "1"), ("0.49", "0"), ("793", "793")],
)
def test_round_kwh_half_up(value, expected):
    assert round_kwh(D(value)) == D(expected)


def test_consumption_from_readings_whole_kwh():
    """4709,5→5343,0 = 633,5 → 634 (FV 408…); 5343,0→6136,3 = 793,3 → 793 (FV 470…)."""
    z = [Zone.ALL]
    assert consumption_from_readings({Zone.ALL: D("4709.5")}, {Zone.ALL: D("5343.0")}, z) == {Zone.ALL: D("634")}
    assert consumption_from_readings({Zone.ALL: D("5343.0")}, {Zone.ALL: D("6136.3")}, z) == {Zone.ALL: D("793")}


def test_consumption_from_readings_zones_negative_and_missing():
    starts = {Zone.DAY: D("100.4"), Zone.NIGHT: D("50.5")}
    ends = {Zone.DAY: D("200.0"), Zone.NIGHT: D("90.0")}
    assert consumption_from_readings(starts, ends, [Zone.DAY, Zone.NIGHT]) == {
        Zone.DAY: D("100"),    # 99,6 → 100
        Zone.NIGHT: D("40"),   # 39,5 → 40 (połówka w górę)
    }
    # odczyt końcowy mniejszy od początkowego → 0, nigdy ujemne
    assert consumption_from_readings({Zone.ALL: D("10")}, {Zone.ALL: D("5")}, [Zone.ALL]) == {Zone.ALL: D("0")}
    # strefa bez kompletu odczytów jest pomijana
    assert consumption_from_readings({Zone.DAY: D("1")}, {Zone.DAY: D("3")}, [Zone.DAY, Zone.NIGHT]) == {Zone.DAY: D("2")}


def test_invoice_470000065575_exact():
    """Faktura PGE 470000065575: G11, 21.07–20.09.2026, 793 kWh — CO DO GROSZA.

    Odczyty 5343,0 → 6136,3 (różnica 793,3) PGE rozlicza jako 793 kWh. Opłaty stałe
    za 2 pełne mc (01.08–30.09), opłata mocowa seg.4 z rocznego zużycia 3632 kWh.
    Bez zaokrąglenia zużycia wyszłoby 781,46 / 179,74 / 961,20 zł (o 34 gr za dużo).
    """
    g11 = load_builtin_profiles()["pge_g11"].with_overrides(
        {"oplata_mocowa_stala": power_fee_rate_for(D("3632"), DEFAULT_SEGMENT_RATES_2026)}
    )
    cons = Consumption(
        consumption_from_readings({Zone.ALL: D("5343.0")}, {Zone.ALL: D("6136.3")}, [Zone.ALL])
    )
    bp = BillingPeriod.from_dates(date(2026, 7, 21), date(2026, 9, 20), whole_months=True)
    bill = calculate(g11, cons, bp)

    expected = {
        "energia_czynna": "399.04",
        "oplata_dystr_sieciowa": "275.09",
        "oplata_dystr_jakosciowa": "26.33",
        "oplata_kogeneracyjna": "2.38",
        "oplata_oze": "5.79",
        "oplata_mocowa_stala": "48.10",
        "oplata_stala_dystr": "19.96",
        "abonament_dystr": "4.50",
    }
    for key, net in expected.items():
        assert bill.line(key).net == D(net), key
    assert (bill.net, bill.vat, bill.gross) == (D("781.19"), D("179.67"), D("960.86"))
