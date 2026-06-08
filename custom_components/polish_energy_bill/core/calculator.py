"""Kalkulator rachunku za prąd.

Reguła zaokrąglania zgodna z polskimi fakturami: każda pozycja zaokrąglana
do grosza (ROUND_HALF_UP), VAT liczony od zaokrąglonej sumy netto w danej stawce.
Dzięki temu suma pozycji = wartość na fakturze co do grosza.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .models import (
    BillingPeriod,
    Consumption,
    Group,
    TariffPosition,
    TariffProfile,
    Unit,
)

CENT = Decimal("0.01")


def round_pln(value: Decimal) -> Decimal:
    """Zaokrąglenie do grosza, połówki w górę (jak na fakturze)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class LineItem:
    """Wyliczona pozycja rachunku."""

    key: str
    name: str
    group: Group
    quantity: Decimal       # ilość w jednostce pozycji (kWh, MWh, mc, dni)
    unit: Unit
    rate: Decimal           # cena jednostkowa netto
    net: Decimal            # należność netto (zaokrąglona do grosza)
    vat_rate: Decimal
    vat: Decimal            # kwota VAT (informacyjnie, per pozycja)
    gross: Decimal          # brutto = net + vat

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "group": self.group.value,
            "quantity": float(self.quantity),
            "unit": self.unit.value,
            "rate": float(self.rate),
            "net": float(self.net),
            "vat_rate": float(self.vat_rate),
            "vat": float(self.vat),
            "gross": float(self.gross),
        }


@dataclass(frozen=True, slots=True)
class Bill:
    """Kompletny rachunek."""

    lines: tuple[LineItem, ...]
    net: Decimal
    vat: Decimal
    gross: Decimal
    consumption_kwh: Decimal = Decimal("0")
    currency: str = "PLN"

    def group_net(self, group: Group) -> Decimal:
        return round_pln(sum((l.net for l in self.lines if l.group is group), Decimal("0")))

    def line(self, key: str) -> LineItem | None:
        return next((l for l in self.lines if l.key == key), None)

    @property
    def variable_gross(self) -> Decimal:
        """Brutto części zależnej od zużycia (per_kwh + per_mwh)."""
        return round_pln(
            sum((l.gross for l in self.lines if l.unit.is_consumption_based), Decimal("0"))
        )

    @property
    def fixed_gross(self) -> Decimal:
        """Brutto opłat stałych (niezależnych od zużycia)."""
        return round_pln(
            sum((l.gross for l in self.lines if not l.unit.is_consumption_based), Decimal("0"))
        )

    @property
    def variable_unit_gross(self) -> Decimal:
        """Średni koszt brutto 1 kWh w części zmiennej [zł/kWh]."""
        if self.consumption_kwh == 0:
            return self.unit_rate_gross
        return (self.variable_gross / self.consumption_kwh).quantize(Decimal("0.0001"))

    @property
    def unit_rate_gross(self) -> Decimal:
        """Stawka brutto za 1 kWh części zmiennej, liczona wprost z cen [zł/kWh].

        Niezależna od poziomu zużycia (działa też przy zużyciu 0) — używana
        jako mnożnik na wykresach kosztu opartych o realny licznik.
        """
        total = Decimal("0")
        for l in self.lines:
            if l.unit is Unit.PER_KWH:
                total += l.rate * (Decimal("1") + l.vat_rate)
            elif l.unit is Unit.PER_MWH:
                total += (l.rate / Decimal("1000")) * (Decimal("1") + l.vat_rate)
        return total.quantize(Decimal("0.0001"))

    def as_dict(self) -> dict:
        return {
            "currency": self.currency,
            "consumption_kwh": float(self.consumption_kwh),
            "net": float(self.net),
            "vat": float(self.vat),
            "gross": float(self.gross),
            "by_group": {
                g.value: float(self.group_net(g))
                for g in Group
                if any(l.group is g for l in self.lines)
            },
            "lines": [l.as_dict() for l in self.lines],
        }


def _quantity(pos: TariffPosition, consumption: Consumption, period: BillingPeriod) -> Decimal:
    """Ilość w jednostce danej pozycji."""
    if pos.unit is Unit.PER_KWH:
        return consumption.kwh(pos.zone)
    if pos.unit is Unit.PER_MWH:
        return consumption.kwh(pos.zone) / Decimal("1000")
    if pos.unit is Unit.PER_MONTH:
        return period.months
    if pos.unit is Unit.PER_DAY:
        return Decimal(period.days)
    if pos.unit is Unit.FLAT:
        return Decimal("1")
    raise ValueError(f"Nieznana jednostka: {pos.unit}")


def calculate(
    profile: TariffProfile,
    consumption: Consumption,
    period: BillingPeriod | None = None,
) -> Bill:
    """Liczy rachunek z profilu, zużycia i okresu.

    Każda włączona pozycja -> jedna linia. Netto zaokrąglane do grosza per
    pozycja; VAT liczony od zsumowanego netto osobno dla każdej stawki VAT.
    """
    period = period or BillingPeriod()
    lines: list[LineItem] = []

    for pos in profile.positions:
        if not pos.enabled:
            continue
        qty = _quantity(pos, consumption, period)
        net = round_pln(qty * pos.rate)
        vat = round_pln(net * pos.vat)  # informacyjnie, per pozycja
        lines.append(
            LineItem(
                key=pos.key, name=pos.name, group=pos.group,
                quantity=qty, unit=pos.unit, rate=pos.rate,
                net=net, vat_rate=pos.vat, vat=vat, gross=net + vat,
            )
        )

    net_total = sum((l.net for l in lines), Decimal("0"))
    # VAT liczony od zsumowanego netto osobno dla każdej stawki VAT.
    vat_total = Decimal("0")
    for rate in sorted({l.vat_rate for l in lines}):
        net_in_rate = sum((l.net for l in lines if l.vat_rate == rate), Decimal("0"))
        vat_total += round_pln(net_in_rate * rate)

    return Bill(
        lines=tuple(lines),
        net=net_total,
        vat=vat_total,
        gross=net_total + vat_total,
        consumption_kwh=consumption.total_kwh,
        currency=profile.currency,
    )
