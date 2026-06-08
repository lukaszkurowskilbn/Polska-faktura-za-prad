"""Czyste modele danych dla kalkulatora rachunku.

Zero zależności od Home Assistant. Wszystko liczone na Decimal,
bo pieniądze i ułamki groszy nie wybaczają floatów.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class Unit(str, Enum):
    """Jednostka rozliczeniowa pozycji."""

    PER_KWH = "per_kwh"      # mnożone przez zużycie [kWh]
    PER_MWH = "per_mwh"      # mnożone przez zużycie [MWh] (zużycie_kWh / 1000)
    PER_MONTH = "per_month"  # stała miesięczna (mnożona przez liczbę miesięcy okresu)
    PER_DAY = "per_day"      # stała dzienna (mnożona przez liczbę dni okresu)
    FLAT = "flat"            # jednorazowa, niezależna od czasu i zużycia

    @property
    def is_consumption_based(self) -> bool:
        return self in (Unit.PER_KWH, Unit.PER_MWH)


class Group(str, Enum):
    """Grupa pozycji — do agregacji i czytelności rachunku."""

    SALE = "sale"                  # sprzedaż energii (obrót)
    DISTRIBUTION = "distribution"  # dystrybucja (OSD)
    TAX = "tax"                    # podatki / opłaty parapodatkowe (akcyza itd.)
    OTHER = "other"


class Zone(str, Enum):
    """Strefa czasowa taryfy.

    ALL  – jednostrefowa / pozycja niezależna od strefy (opłaty stałe).
    DAY/NIGHT/PEAK/OFF_PEAK – strefy taryf wielostrefowych (G12, G12w...).
    """

    ALL = "all"
    DAY = "day"
    NIGHT = "night"
    PEAK = "peak"
    OFF_PEAK = "off_peak"


@dataclass(frozen=True, slots=True)
class TariffPosition:
    """Pojedyncza pozycja na rachunku.

    To jest atom systemu. Polski rachunek to po prostu lista takich pozycji.
    Gdy URE/sprzedawca zmieni stawkę — zmienia się tylko `rate`.
    """

    key: str                         # stabilny identyfikator, np. "energia_czynna"
    name: str                        # nazwa wyświetlana, jak na fakturze
    unit: Unit
    rate: Decimal                    # cena jednostkowa NETTO [zł]
    group: Group = Group.OTHER
    vat: Decimal = Decimal("0.23")   # stawka VAT jako ułamek (0.23 = 23%)
    zone: Zone = Zone.ALL
    enabled: bool = True

    def __post_init__(self) -> None:
        # Wymuszamy Decimal nawet jeśli ktoś poda str/float/int z YAML.
        object.__setattr__(self, "rate", _dec(self.rate))
        object.__setattr__(self, "vat", _dec(self.vat))

    def with_rate(self, rate: Decimal | str | float) -> "TariffPosition":
        """Zwraca kopię z nadpisaną stawką (override z UI)."""
        return TariffPosition(
            key=self.key, name=self.name, unit=self.unit, rate=_dec(rate),
            group=self.group, vat=self.vat, zone=self.zone, enabled=self.enabled,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TariffPosition":
        return cls(
            key=data["key"],
            name=data.get("name", data["key"]),
            unit=Unit(data["unit"]),
            rate=_dec(data["rate"]),
            group=Group(data.get("group", "other")),
            vat=_dec(data.get("vat", "0.23")),
            zone=Zone(data.get("zone", "all")),
            enabled=bool(data.get("enabled", True)),
        )


@dataclass(frozen=True, slots=True)
class TariffProfile:
    """Komplet pozycji dla danego sprzedawcy + taryfy (np. PGE G11)."""

    key: str
    name: str
    seller: str
    tariff: str                      # symbol taryfy: G11, G12, G12w...
    zones: tuple[Zone, ...]          # strefy obecne w tej taryfie
    positions: tuple[TariffPosition, ...]
    currency: str = "PLN"

    def position(self, key: str) -> TariffPosition | None:
        return next((p for p in self.positions if p.key == key), None)

    def with_overrides(self, overrides: dict[str, Decimal | str | float]) -> "TariffProfile":
        """Nadpisuje stawki wskazanych pozycji (po kluczu). Reszta bez zmian."""
        return self.customize(rate_overrides=overrides)

    def customize(
        self,
        rate_overrides: dict[str, Decimal | str | float] | None = None,
        enabled_overrides: dict[str, bool] | None = None,
    ) -> "TariffProfile":
        """Zwraca profil z nadpisanymi stawkami i/lub stanem włączenia pozycji.

        Używane przez warstwę HA: stawki z encji number, włączenie z opcji.
        """
        rate_overrides = rate_overrides or {}
        enabled_overrides = enabled_overrides or {}
        new_positions = []
        for p in self.positions:
            rate = rate_overrides.get(p.key, p.rate)
            enabled = enabled_overrides.get(p.key, p.enabled)
            new_positions.append(
                TariffPosition(
                    key=p.key, name=p.name, unit=p.unit, rate=_dec(rate),
                    group=p.group, vat=p.vat, zone=p.zone, enabled=enabled,
                )
            )
        return TariffProfile(
            key=self.key, name=self.name, seller=self.seller, tariff=self.tariff,
            zones=self.zones, positions=tuple(new_positions), currency=self.currency,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TariffProfile":
        positions = tuple(TariffPosition.from_dict(p) for p in data["positions"])
        zones = tuple(Zone(z) for z in data.get("zones", ["all"]))
        return cls(
            key=data["key"],
            name=data.get("name", data["key"]),
            seller=data.get("seller", "?"),
            tariff=data.get("tariff", "?"),
            zones=zones,
            positions=positions,
            currency=data.get("currency", "PLN"),
        )


@dataclass(frozen=True, slots=True)
class BillingPeriod:
    """Parametry okresu rozliczeniowego potrzebne do pozycji czasowych."""

    days: int = 30                   # liczba dni okresu (dla PER_DAY)
    months: Decimal = Decimal("1")   # liczba miesięcy (dla PER_MONTH, ułamki dozwolone)

    def __post_init__(self) -> None:
        object.__setattr__(self, "months", _dec(self.months))

    @classmethod
    def from_dates(cls, start, end) -> "BillingPeriod":
        """Liczy okres z zakresu dat (date/datetime).

        - days  = różnica dni (min. 1),
        - months = miesiące kalendarzowe + ułamek z dni, tak by typowy okres
          rozliczeniowy trafiał w naliczenia faktury (np. 31.01→31.03 = 2,0).
        """
        days = (end - start).days
        if days < 1:
            days = 1
        months = (
            Decimal((end.year - start.year) * 12 + (end.month - start.month))
            + Decimal(end.day - start.day) / Decimal("30")
        )
        if months <= 0:
            months = Decimal(days) / Decimal("30.4375")
        return cls(days=days, months=months)


@dataclass(frozen=True, slots=True)
class Consumption:
    """Zużycie energii w okresie, w rozbiciu na strefy [kWh].

    Dla taryfy jednostrefowej wystarczy {Zone.ALL: x}.
    """

    by_zone: dict[Zone, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "by_zone", {z: _dec(v) for z, v in self.by_zone.items()}
        )

    @property
    def total_kwh(self) -> Decimal:
        return sum(self.by_zone.values(), Decimal("0"))

    def kwh(self, zone: Zone) -> Decimal:
        """Zużycie przypisane do strefy pozycji.

        Pozycja w strefie ALL (np. opłata sieciowa naliczana od całości)
        dostaje sumę wszystkich stref; pozycja strefowa — tylko swoją strefę.
        """
        if zone is Zone.ALL:
            return self.total_kwh
        return self.by_zone.get(zone, Decimal("0"))


def _dec(value: Decimal | str | float | int) -> Decimal:
    """Bezpieczna konwersja na Decimal (float idzie przez str, by uniknąć szumu)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)
