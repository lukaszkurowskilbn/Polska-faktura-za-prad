"""Weryfikacja faktury i „faktura teoretyczna” — czysta logika, bez Home Assistant.

1. `check_invoice` — użytkownik wpisuje z faktury okres, zużycie i kwotę do zapłaty;
   liczymy ten sam rachunek kalkulatorem i pokazujemy różnicę.
2. `theoretical_bill` / `project_consumption` — rachunek za CAŁY okres (opłaty stałe
   za pełne miesiące, jak na fakturze) przed jego końcem: ze zużyciem do dziś albo
   z zużyciem przeskalowanym do końca okresu wg średniej dziennej.

Założenie: taryfa jednostrefowa (strefa ALL) — z faktury wpisujemy jedną liczbę kWh.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .calculator import Bill, calculate
from .models import BillingPeriod, Consumption, TariffProfile, Zone, round_kwh

STATUS_MATCH = "zgodna"
STATUS_DIFF = "odchyłka"
STATUS_NO_DECLARED = "brak kwoty z faktury"

# Różnica do 1 grosza to zaokrąglenia, nie rozbieżność stawek.
MATCH_TOLERANCE = Decimal("0.01")
MIN_ELAPSED_SECONDS = 24 * 3600  # poniżej doby średnia dzienna nic nie mówi


class InvoiceError(ValueError):
    """Niepoprawne dane faktury / okresu."""


@dataclass(frozen=True)
class InvoiceCheck:
    bill: Bill
    kwh: Decimal                       # po zaokrągleniu do pełnych kWh
    days: int
    months: Decimal
    declared_gross: Decimal | None
    difference: Decimal | None         # wyliczona − z faktury
    status: str


def add_months(value: date, months: int) -> date:
    """Dodaje miesiące, przycinając dzień do końca miesiąca (31.01 + 1 → 28.02)."""
    index = value.year * 12 + (value.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def theoretical_bill(
    profile: TariffProfile, kwh: Decimal, start: date, end: date
) -> Bill:
    """Rachunek za zamknięty okres [start, end]: pełne miesiące opłat stałych."""
    period = BillingPeriod.from_dates(start, end, whole_months=True)
    return calculate(profile, Consumption({Zone.ALL: kwh}), period)


def check_invoice(
    profile: TariffProfile,
    kwh: Decimal,
    start: date,
    end: date,
    declared_gross: Decimal | None,
) -> InvoiceCheck:
    """Liczy rachunek z danych faktury i porównuje z kwotą z faktury."""
    if end <= start:
        raise InvoiceError("Data końca okresu musi być późniejsza niż początku.")
    if kwh < 0:
        raise InvoiceError("Zużycie nie może być ujemne.")

    kwh = round_kwh(kwh)  # PGE rozlicza w pełnych kWh
    period = BillingPeriod.from_dates(start, end, whole_months=True)
    bill = calculate(profile, Consumption({Zone.ALL: kwh}), period)

    if declared_gross is None or declared_gross <= 0:
        return InvoiceCheck(bill, kwh, period.days, period.months, None, None, STATUS_NO_DECLARED)

    difference = bill.gross - declared_gross
    status = STATUS_MATCH if abs(difference) <= MATCH_TOLERANCE else STATUS_DIFF
    return InvoiceCheck(bill, kwh, period.days, period.months, declared_gross, difference, status)


def project_consumption(
    kwh_so_far: Decimal, start: datetime, now: datetime, end: datetime
) -> Decimal | None:
    """Zużycie przeskalowane do końca okresu wg średniej dziennej (pełne kWh).

    None, gdy za mało danych: przed startem albo przed upływem pierwszej doby.
    Po końcu okresu zwraca faktyczne zużycie.
    """
    if end <= start:
        raise InvoiceError("Koniec okresu musi być późniejszy niż początek.")
    if now >= end:
        return round_kwh(kwh_so_far)
    elapsed = (now - start).total_seconds()
    if elapsed < MIN_ELAPSED_SECONDS:
        return None
    total = (end - start).total_seconds()
    return round_kwh(kwh_so_far * Decimal(str(total)) / Decimal(str(elapsed)))
