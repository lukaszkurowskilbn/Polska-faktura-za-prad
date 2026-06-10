"""Testy nakładki ETS — obie metody, bezlitośnie na realnej fakturze PGE.

Uruchom: pytest -q  (z katalogu repo)
"""

from decimal import Decimal as D

import pytest

from core import (
    BillingPeriod,
    Consumption,
    EtsMethod,
    EtsParams,
    Unit,
    Zone,
    calculate,
    estimate_ets,
    load_builtin_profiles,
)

# Parametry jak domyślne w integracji (wartości startowe edytowalnych pól).
PARAMS = EtsParams(
    percent_share=D("0.55"),       # 55% (PGE IV kw. 2026)
    emission_factor=D("0.5426"),   # t CO₂/MWh (PGE struktura paliw 2025)
    eua_price_eur=D("80"),
    eur_pln=D("4.30"),
)


def _energy_from_bill(bill):
    """Odtworzenie ekstrakcji z coordinatora: pozycje 'energia czynna'."""
    lines = [l for l in bill.lines if l.key.startswith("energia_czynna")]
    energy_net = sum((l.net for l in lines), D("0"))
    energy_gross = sum((l.gross for l in lines), D("0"))
    vat = lines[0].vat_rate if lines else D("0.23")
    return energy_net, energy_gross, vat


# --------------------------------------------------------------------------
# Metoda procentowa
# --------------------------------------------------------------------------

def test_percent_on_real_invoice_g11():
    """315 kWh, G11: energia czynna 158,51 netto → ETS 55% = 87,18 netto."""
    g11 = load_builtin_profiles()["pge_g11"]
    bill = calculate(g11, Consumption({Zone.ALL: D("315")}), BillingPeriod(months=D("1")))
    e_net, e_gross, vat = _energy_from_bill(bill)

    est = estimate_ets(
        method=EtsMethod.PERCENT,
        params=PARAMS,
        energy_net=e_net,
        energy_gross=e_gross,
        energy_unit_rate_net=D("0.50320"),
        energy_vat_rate=vat,
        consumption_kwh=bill.consumption_kwh,
        bill_gross=bill.gross,
    )
    assert est.net == D("87.18")          # round(158,51 × 0,55)
    assert est.vat == D("20.05")          # round(87,18 × 0,23)
    assert est.gross == D("107.23")
    # Stawka z ceny: 0,55 × 0,50320 × 1,23.
    assert est.rate_gross == D("0.3404")
    # Udział w koszcie energii ≈ 55% (różnica z zaokrągleń grosza).
    assert abs(est.share_of_energy - D("0.55")) <= D("0.001")


def test_percent_share_tracks_percent_field():
    """Zmiana udziału (pole edytowalne) zmienia koszt liniowo."""
    g11 = load_builtin_profiles()["pge_g11"]
    bill = calculate(g11, Consumption({Zone.ALL: D("315")}), BillingPeriod(months=D("1")))
    e_net, e_gross, vat = _energy_from_bill(bill)
    p = EtsParams(D("0.40"), D("0.5426"), D("80"), D("4.30"))
    est = estimate_ets(
        method=EtsMethod.PERCENT, params=p,
        energy_net=e_net, energy_gross=e_gross, energy_unit_rate_net=D("0.50320"),
        energy_vat_rate=vat, consumption_kwh=bill.consumption_kwh, bill_gross=bill.gross,
    )
    assert est.net == D("63.40")          # round(158,51 × 0,40)


# --------------------------------------------------------------------------
# Metoda fizyczna (emisja × EUA × kurs)
# --------------------------------------------------------------------------

def test_emission_on_real_invoice_g11():
    """315 kWh × 0,5426 t/MWh × 80 EUR × 4,30 PLN = 58,80 netto."""
    g11 = load_builtin_profiles()["pge_g11"]
    bill = calculate(g11, Consumption({Zone.ALL: D("315")}), BillingPeriod(months=D("1")))
    e_net, e_gross, vat = _energy_from_bill(bill)

    est = estimate_ets(
        method=EtsMethod.EMISSION,
        params=PARAMS,
        energy_net=e_net,
        energy_gross=e_gross,
        energy_unit_rate_net=D("0.50320"),
        energy_vat_rate=vat,
        consumption_kwh=bill.consumption_kwh,
        bill_gross=bill.gross,
    )
    assert est.net == D("58.80")
    assert est.vat == D("13.52")
    assert est.gross == D("72.32")
    assert est.co2_kg == D("170.919")     # 315 × 0,5426
    assert est.rate_gross == D("0.2296")  # 0,5426×80×4,30/1000 ×1,23


def test_emission_scales_with_consumption():
    g11 = load_builtin_profiles()["pge_g11"]
    bill = calculate(g11, Consumption({Zone.ALL: D("0")}), BillingPeriod(months=D("1")))
    e_net, e_gross, vat = _energy_from_bill(bill)
    est = estimate_ets(
        method=EtsMethod.EMISSION, params=PARAMS,
        energy_net=e_net, energy_gross=e_gross, energy_unit_rate_net=D("0.50320"),
        energy_vat_rate=vat, consumption_kwh=D("0"), bill_gross=bill.gross,
    )
    assert est.net == D("0.00")
    assert est.co2_kg == D("0.000")
    # Stawka z ceny działa też przy zerowym zużyciu.
    assert est.rate_gross == D("0.2296")


# --------------------------------------------------------------------------
# Niezależność: obie metody policzone zawsze (do porównania na wykresie)
# --------------------------------------------------------------------------

def test_both_methods_always_present():
    g11 = load_builtin_profiles()["pge_g11"]
    bill = calculate(g11, Consumption({Zone.ALL: D("315")}), BillingPeriod(months=D("1")))
    e_net, e_gross, vat = _energy_from_bill(bill)
    est = estimate_ets(
        method=EtsMethod.PERCENT, params=PARAMS,
        energy_net=e_net, energy_gross=e_gross, energy_unit_rate_net=D("0.50320"),
        energy_vat_rate=vat, consumption_kwh=bill.consumption_kwh, bill_gross=bill.gross,
    )
    assert est.percent_gross == D("107.23")
    assert est.emission_gross == D("72.32")
    # Wybrana metoda = procentowa.
    assert est.gross == est.percent_gross


def test_share_of_bill_below_one():
    g11 = load_builtin_profiles()["pge_g11"]
    bill = calculate(g11, Consumption({Zone.ALL: D("315")}), BillingPeriod(months=D("1")))
    e_net, e_gross, vat = _energy_from_bill(bill)
    est = estimate_ets(
        method=EtsMethod.PERCENT, params=PARAMS,
        energy_net=e_net, energy_gross=e_gross, energy_unit_rate_net=D("0.50320"),
        energy_vat_rate=vat, consumption_kwh=bill.consumption_kwh, bill_gross=bill.gross,
    )
    # ETS to część rachunku — udział w (0, 1).
    assert D("0") < est.share_of_bill < D("1")
    # I jest sensownie duży (energia czynna to spory kawałek rachunku).
    assert est.share_of_bill > D("0.15")


def test_g12_sums_both_energy_zones():
    """G12: baza % to suma energii czynnej dzień+noc."""
    g12 = load_builtin_profiles()["pge_g12"]
    bill = calculate(
        g12, Consumption({Zone.DAY: D("100"), Zone.NIGHT: D("200")}),
        BillingPeriod(months=D("1")),
    )
    e_net, e_gross, vat = _energy_from_bill(bill)
    # dzień 100×0,55=55,00 ; noc 200×0,40=80,00 → 135,00 netto energii czynnej.
    assert e_net == D("135.00")
    est = estimate_ets(
        method=EtsMethod.PERCENT, params=PARAMS,
        energy_net=e_net, energy_gross=e_gross,
        energy_unit_rate_net=D("0.55000") + D("0.40000"),
        energy_vat_rate=vat, consumption_kwh=bill.consumption_kwh, bill_gross=bill.gross,
    )
    assert est.net == D("74.25")          # round(135,00 × 0,55)
