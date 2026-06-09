"""Testy rdzenia kalkulatora — bezlitośnie, na realnej fakturze PGE.

Uruchom: pytest -q  (z katalogu repo)
"""

from decimal import Decimal as D

import pytest

from core import (
    BillingPeriod,
    Consumption,
    Group,
    TariffPosition,
    TariffProfile,
    Unit,
    Zone,
    calculate,
    load_builtin_profiles,
    round_pln,
)


# --------------------------------------------------------------------------
# Zaokrąglanie
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [
        ("158.508", "158.51"),   # połówka w górę
        ("109.2735", "109.27"),
        ("0.945", "0.95"),
        ("2.2995", "2.30"),
        ("122.1488", "122.15"),
        ("0.005", "0.01"),       # HALF_UP, nie bankers
    ],
)
def test_round_pln_half_up(value, expected):
    assert round_pln(D(value)) == D(expected)


# --------------------------------------------------------------------------
# Jednostki pozycji
# --------------------------------------------------------------------------

def _profile(*positions):
    return TariffProfile(
        key="t", name="t", seller="t", tariff="t",
        zones=(Zone.ALL,), positions=positions,
    )


def test_per_kwh():
    prof = _profile(
        TariffPosition("e", "energia", Unit.PER_KWH, D("0.50320"), Group.SALE)
    )
    bill = calculate(prof, Consumption({Zone.ALL: D("315")}))
    assert bill.line("e").net == D("158.51")


def test_per_mwh_uses_kwh_over_1000():
    prof = _profile(
        TariffPosition("oze", "OZE", Unit.PER_MWH, D("7.30000"), Group.SALE)
    )
    bill = calculate(prof, Consumption({Zone.ALL: D("315")}))
    # 0,315 MWh * 7,30 = 2,2995 -> 2,30
    assert bill.line("oze").net == D("2.30")


def test_per_month_scales_with_months():
    prof = _profile(
        TariffPosition("stala", "stała", Unit.PER_MONTH, D("9.98000"), Group.DISTRIBUTION)
    )
    bill = calculate(prof, Consumption({Zone.ALL: D("0")}), BillingPeriod(months=D("2")))
    assert bill.line("stala").net == D("19.96")


def test_per_day_scales_with_days():
    prof = _profile(
        TariffPosition("d", "dzienna", Unit.PER_DAY, D("1.00"), Group.OTHER)
    )
    bill = calculate(prof, Consumption({Zone.ALL: D("0")}), BillingPeriod(days=59))
    assert bill.line("d").net == D("59.00")


def test_disabled_position_skipped():
    prof = _profile(
        TariffPosition("a", "akcyza", Unit.PER_MWH, D("5"), Group.TAX, enabled=False)
    )
    bill = calculate(prof, Consumption({Zone.ALL: D("1000")}))
    assert bill.line("a") is None
    assert bill.net == D("0")


# --------------------------------------------------------------------------
# Strefy (taryfa wielostrefowa)
# --------------------------------------------------------------------------

def test_zonal_positions_use_their_zone():
    prof = TariffProfile(
        key="g12", name="g12", seller="x", tariff="G12",
        zones=(Zone.DAY, Zone.NIGHT),
        positions=(
            TariffPosition("ed", "dzień", Unit.PER_KWH, D("0.60"), Group.SALE, zone=Zone.DAY),
            TariffPosition("en", "noc", Unit.PER_KWH, D("0.30"), Group.SALE, zone=Zone.NIGHT),
            TariffPosition("oze", "OZE", Unit.PER_MWH, D("7.30"), Group.SALE, zone=Zone.ALL),
        ),
    )
    bill = calculate(prof, Consumption({Zone.DAY: D("100"), Zone.NIGHT: D("200")}))
    assert bill.line("ed").net == D("60.00")    # 100 * 0,60
    assert bill.line("en").net == D("60.00")    # 200 * 0,30
    # OZE w strefie ALL liczy się od sumy 300 kWh = 0,3 MWh * 7,30 = 2,19
    assert bill.line("oze").net == D("2.19")
    assert bill.consumption_kwh == D("300")


def test_vat_computed_per_rate_on_summed_net():
    # Dwie pozycje 23%: VAT liczony od sumy netto, nie per linia.
    prof = _profile(
        TariffPosition("a", "a", Unit.PER_KWH, D("0.10"), Group.SALE),
        TariffPosition("b", "b", Unit.PER_MONTH, D("0.10"), Group.SALE),
    )
    bill = calculate(prof, Consumption({Zone.ALL: D("1")}))
    # net = 0,10 + 0,10 = 0,20; VAT = 0,20*0,23 = 0,046 -> 0,05
    assert bill.net == D("0.20")
    assert bill.vat == D("0.05")
    assert bill.gross == D("0.25")


# --------------------------------------------------------------------------
# Profile wbudowane
# --------------------------------------------------------------------------

def test_builtin_profiles_load():
    profiles = load_builtin_profiles()
    assert set(profiles) == {"pge_g11", "pge_g12", "pge_g12w", "tauron_g12w"}
    g11 = profiles["pge_g11"]
    assert g11.tariff == "G11"
    assert g11.position("energia_czynna").rate == D("0.50320")


def test_override_changes_rate():
    g11 = load_builtin_profiles()["pge_g11"]
    customized = g11.customize(rate_overrides={"energia_czynna": "0.60000"})
    assert customized.position("energia_czynna").rate == D("0.60000")
    # oryginał nietknięty
    assert g11.position("energia_czynna").rate == D("0.50320")


# --------------------------------------------------------------------------
# Test integracyjny: realna faktura PGE 10819154/60R/2026
# --------------------------------------------------------------------------

def test_real_invoice_pge_g11():
    """Odtworzenie faktury: 667 kWh, okres ~2 mies.

    Faktura: netto 668,61 / VAT 153,78 / brutto 822,39.
    Nasz spójny kalkulator daje 668,58 / 153,77 / 822,35 — różnica 3-4 grosze
    wynika z tego, że PGE zaokrągla per odczyt (dwa odczyty w okresie) oraz
    liczy energię z innego zaokrąglenia zużycia niż dystrybucję. To artefakt
    faktury, nie błąd. Trzymamy tolerancję 0,10 zł na sumie.
    """
    g11 = load_builtin_profiles()["pge_g11"]
    bill = calculate(
        g11,
        Consumption({Zone.ALL: D("667")}),
        BillingPeriod(days=59, months=D("2")),
    )
    assert abs(bill.net - D("668.61")) <= D("0.10")
    assert abs(bill.gross - D("822.39")) <= D("0.15")
    # brutto = netto + VAT, dokładnie
    assert bill.gross == bill.net + bill.vat


def test_invoice_individual_positions_exact():
    """Pojedyncze pozycje lutego (315 kWh, 1 mc) trafiają co do grosza."""
    g11 = load_builtin_profiles()["pge_g11"]
    bill = calculate(
        g11, Consumption({Zone.ALL: D("315")}), BillingPeriod(months=D("1"))
    )
    assert bill.line("energia_czynna").net == D("158.51")
    assert bill.line("oplata_kogeneracyjna").net == D("0.95")
    assert bill.line("oplata_oze").net == D("2.30")
    assert bill.line("oplata_dystr_sieciowa").net == D("109.27")
    assert bill.line("oplata_dystr_jakosciowa").net == D("10.46")
    assert bill.line("oplata_stala_dystr").net == D("9.98")
    assert bill.line("abonament_dystr").net == D("2.25")
    assert bill.line("oplata_mocowa_stala").net == D("24.05")
