"""Testy weryfikacji faktury i faktury teoretycznej (czysta logika, bez HA)."""

from datetime import date, datetime
from decimal import Decimal as D

import pytest

from core import (
    DEFAULT_SEGMENT_RATES_2026,
    load_builtin_profiles,
    power_fee_rate_for,
)
from core.invoice import (
    STATUS_DIFF,
    STATUS_MATCH,
    STATUS_NO_DECLARED,
    InvoiceError,
    add_months,
    check_invoice,
    project_consumption,
    theoretical_bill,
)


@pytest.fixture(scope="module")
def g11():
    # Opłata mocowa seg.4 (roczne zużycie 3632 kWh) — jak na fakturze 470000065575.
    return load_builtin_profiles()["pge_g11"].with_overrides(
        {"oplata_mocowa_stala": power_fee_rate_for(D("3632"), DEFAULT_SEGMENT_RATES_2026)}
    )


def test_check_invoice_matches_real_invoice_to_the_grosz(g11):
    # Faktura PGE 470000065575: 21.07–20.09.2026, 793 kWh, do zapłaty 960,86 zł.
    result = check_invoice(g11, D("793"), date(2026, 7, 21), date(2026, 9, 20), D("960.86"))
    assert result.bill.gross == D("960.86")
    assert result.difference == D("0.00")
    assert result.status == STATUS_MATCH
    assert (result.days, result.months) == (61, D("2"))


def test_check_invoice_rounds_kwh_to_whole(g11):
    # Wpisane 793,3 kWh PGE rozlicza jako 793.
    result = check_invoice(g11, D("793.3"), date(2026, 7, 21), date(2026, 9, 20), D("960.86"))
    assert result.kwh == D("793")
    assert result.status == STATUS_MATCH


def test_check_invoice_reports_difference(g11):
    result = check_invoice(g11, D("793"), date(2026, 7, 21), date(2026, 9, 20), D("950.00"))
    assert result.difference == D("10.86")
    assert result.status == STATUS_DIFF


def test_one_grosz_is_still_a_match(g11):
    result = check_invoice(g11, D("793"), date(2026, 7, 21), date(2026, 9, 20), D("960.85"))
    assert result.difference == D("0.01")
    assert result.status == STATUS_MATCH


def test_missing_declared_amount_still_calculates(g11):
    for declared in (None, D("0")):
        result = check_invoice(g11, D("793"), date(2026, 7, 21), date(2026, 9, 20), declared)
        assert result.status == STATUS_NO_DECLARED
        assert result.difference is None
        assert result.bill.gross == D("960.86")


@pytest.mark.parametrize(
    "start,end,kwh",
    [
        (date(2026, 9, 20), date(2026, 9, 20), D("1")),   # koniec = początek
        (date(2026, 9, 20), date(2026, 7, 21), D("1")),   # odwrócone
        (date(2026, 7, 21), date(2026, 9, 20), D("-1")),  # ujemne zużycie
    ],
)
def test_invalid_input_raises(g11, start, end, kwh):
    with pytest.raises(InvoiceError):
        check_invoice(g11, kwh, start, end, D("100"))


def test_theoretical_bill_uses_whole_months(g11):
    bill = theoretical_bill(g11, D("793"), date(2026, 7, 21), date(2026, 9, 20))
    assert bill.gross == D("960.86")


def test_project_consumption_scales_to_period_end():
    start = datetime(2026, 9, 20)
    end = datetime(2026, 11, 21)  # 62 dni
    now = datetime(2026, 10, 21)  # 31 dni upłynęło = połowa
    assert project_consumption(D("400"), start, now, end) == D("800")
    assert project_consumption(D("401"), start, now, end) == D("802")


def test_project_consumption_rounds_to_whole_kwh():
    start, end = datetime(2026, 9, 20), datetime(2026, 11, 21)
    now = datetime(2026, 9, 30)  # 10 z 62 dni
    # 100 * 62 / 10 = 620
    assert project_consumption(D("100"), start, now, end) == D("620")
    # 33 * 6.2 = 204.6 -> 205
    assert project_consumption(D("33"), start, now, end) == D("205")


def test_project_consumption_refuses_to_guess_early():
    start, end = datetime(2026, 9, 20), datetime(2026, 11, 21)
    assert project_consumption(D("5"), start, datetime(2026, 9, 20, 12), end) is None  # < 1 doba
    assert project_consumption(D("5"), start, datetime(2026, 9, 19), end) is None       # przed startem


def test_project_consumption_after_end_returns_actual():
    start, end = datetime(2026, 9, 20), datetime(2026, 11, 21)
    assert project_consumption(D("812"), start, datetime(2026, 12, 1), end) == D("812")


def test_project_consumption_rejects_bad_period():
    with pytest.raises(InvoiceError):
        project_consumption(D("1"), datetime(2026, 11, 21), datetime(2026, 12, 1), datetime(2026, 9, 20))


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 9, 20), 2) == date(2026, 11, 20)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 12, 31), 2) == date(2027, 2, 28)
