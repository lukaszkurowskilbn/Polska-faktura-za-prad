"""Szacowanie udziału kosztów uprawnień do emisji CO₂ (ETS) w rachunku.

ETS to NIE jest osobna pozycja faktury — koszt uprawnień jest zaszyty w cenie
energii czynnej. Dlatego liczymy go jako nakładkę na gotowy, niezmieniony
rachunek (Bill). Nic w kalkulatorze nie modyfikujemy.

Dwie metody, obie oparte o oficjalne dane sprzedawcy:

PERCENT — udział procentowy kosztu uprawnień w cenie energii czynnej.
    PGE publikuje go kwartalnie w komunikacie (§37 ust. 2 rozporządzenia
    taryfowego). Dla IV kw. 2026 = 55%, w 2025 = 56%. Liczone wprost:
        ETS_netto = udział × wartość_netto(energia_czynna).
    Najbardziej zgodne z tym, co faktycznie jest fakturowane.

EMISSION — fizyczne: ile CO₂ stoi za zużyciem i ile to kosztuje na rynku.
        ETS_netto = zużycie[MWh] × wskaźnik_emisji[t/MWh] × cena_EUA[EUR/t] × kurs[PLN/EUR]
    Wskaźnik emisji z „struktury paliw" PGE 2025 = 0,5426 t CO₂/MWh.
    Pogląd edukacyjny; mniej zgodny z fakturą (darmowe uprawnienia, cena hurtowa).

Wszystkie parametry (udział, wskaźnik, cena EUA, kurs) zmieniają się w czasie,
więc w warstwie HA są edytowalnymi polami — tu przyjmujemy je jako argumenty.

VAT: koszt ETS jest częścią ceny energii czynnej, więc dziedziczy jej stawkę
VAT (zwykle 23%). Brutto = netto × (1 + vat).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .calculator import round_pln
from .models import _dec

KWH_PER_MWH = Decimal("1000")
ZERO = Decimal("0")


class EtsMethod(str, Enum):
    """Metoda szacowania kosztu ETS."""

    PERCENT = "procent"      # udział % w cenie energii czynnej (komunikat PGE)
    EMISSION = "emisja"      # fizyczna: emisja CO₂ × cena uprawnienia EUA


@dataclass(frozen=True, slots=True)
class EtsParams:
    """Parametry szacowania ETS — wszystkie edytowalne w UI, bo się zmieniają.

    percent_share : ułamek (0.55 = 55%) udziału ETS w cenie energii czynnej.
    emission_factor : wskaźnik emisji CO₂ [t/MWh] (= [kg/kWh] liczbowo).
    eua_price_eur : rynkowa cena uprawnienia EUA [EUR/t CO₂].
    eur_pln : kurs [PLN/EUR].
    """

    percent_share: Decimal
    emission_factor: Decimal
    eua_price_eur: Decimal
    eur_pln: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "percent_share", _dec(self.percent_share))
        object.__setattr__(self, "emission_factor", _dec(self.emission_factor))
        object.__setattr__(self, "eua_price_eur", _dec(self.eua_price_eur))
        object.__setattr__(self, "eur_pln", _dec(self.eur_pln))


@dataclass(frozen=True, slots=True)
class EtsEstimate:
    """Wynik szacowania kosztu ETS w okresie rozliczeniowym."""

    method: EtsMethod
    net: Decimal              # koszt ETS netto [PLN] (wybrana metoda)
    vat: Decimal              # VAT od kosztu ETS [PLN]
    gross: Decimal            # koszt ETS brutto [PLN]
    rate_gross: Decimal       # stawka ETS brutto [zł/kWh] z cen (do wykresów)
    co2_kg: Decimal           # masa CO₂ stojąca za zużyciem [kg]
    share_of_bill: Decimal    # udział ETS w rachunku brutto [ułamek 0..1]
    share_of_energy: Decimal  # udział ETS w koszcie energii czynnej brutto [ułamek]
    percent_gross: Decimal    # koszt ETS brutto wg metody % [PLN] (porównawczo)
    emission_gross: Decimal   # koszt ETS brutto wg metody emisyjnej [PLN]

    def as_dict(self) -> dict:
        return {
            "method": self.method.value,
            "net": float(self.net),
            "vat": float(self.vat),
            "gross": float(self.gross),
            "rate_gross": float(self.rate_gross),
            "co2_kg": float(self.co2_kg),
            "share_of_bill": float(self.share_of_bill),
            "share_of_energy": float(self.share_of_energy),
            "share_of_bill_pct": float((self.share_of_bill * 100).quantize(Decimal("0.1"))),
            "percent_gross": float(self.percent_gross),
            "emission_gross": float(self.emission_gross),
        }


def _grossed(net: Decimal, vat_rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    """Zwraca (netto, vat, brutto) z netto i stawki VAT — grosze HALF_UP."""
    net = round_pln(net)
    vat = round_pln(net * vat_rate)
    return net, vat, net + vat


def _percent_net(energy_net: Decimal, params: EtsParams) -> Decimal:
    """Koszt ETS netto metodą udziału procentowego."""
    return energy_net * params.percent_share


def _emission_net(consumption_kwh: Decimal, params: EtsParams) -> Decimal:
    """Koszt ETS netto metodą fizyczną (emisja × cena EUA × kurs)."""
    mwh = consumption_kwh / KWH_PER_MWH
    return mwh * params.emission_factor * params.eua_price_eur * params.eur_pln


def estimate(
    *,
    method: EtsMethod,
    params: EtsParams,
    energy_net: Decimal,
    energy_gross: Decimal,
    energy_unit_rate_net: Decimal,
    energy_vat_rate: Decimal,
    consumption_kwh: Decimal,
    bill_gross: Decimal,
) -> EtsEstimate:
    """Liczy nakładkę ETS na gotowy rachunek.

    energy_net/energy_gross : suma netto/brutto pozycji „energia czynna".
    energy_unit_rate_net : suma stawek netto [zł/kWh] pozycji energii czynnej
        (cena, niezależna od zużycia — baza stawki ETS na wykresach).
    energy_vat_rate : stawka VAT energii czynnej (zwykle 0,23).
    consumption_kwh : zużycie przyjęte do rachunku.
    bill_gross : całość rachunku brutto (mianownik udziału).
    """
    energy_net = _dec(energy_net)
    energy_gross = _dec(energy_gross)
    energy_unit_rate_net = _dec(energy_unit_rate_net)
    energy_vat_rate = _dec(energy_vat_rate)
    consumption_kwh = _dec(consumption_kwh)
    bill_gross = _dec(bill_gross)
    one_plus_vat = Decimal("1") + energy_vat_rate

    # Koszt obiema metodami (porównawczo na wykresie/atrybutach).
    p_net, _p_vat, percent_gross = _grossed(_percent_net(energy_net, params), energy_vat_rate)
    e_net, _e_vat, emission_gross = _grossed(
        _emission_net(consumption_kwh, params), energy_vat_rate
    )

    if method is EtsMethod.PERCENT:
        net, vat, gross = _grossed(_percent_net(energy_net, params), energy_vat_rate)
        # Stawka z ceny: udział × stawka energii czynnej, brutto. Działa przy zużyciu 0.
        rate_gross = (params.percent_share * energy_unit_rate_net * one_plus_vat).quantize(
            Decimal("0.0001")
        )
    else:
        net, vat, gross = _grossed(_emission_net(consumption_kwh, params), energy_vat_rate)
        rate_per_kwh_net = (
            params.emission_factor * params.eua_price_eur * params.eur_pln / KWH_PER_MWH
        )
        rate_gross = (rate_per_kwh_net * one_plus_vat).quantize(Decimal("0.0001"))

    co2_kg = (consumption_kwh * params.emission_factor).quantize(Decimal("0.001"))
    share_of_bill = (gross / bill_gross) if bill_gross > 0 else ZERO
    share_of_energy = (gross / energy_gross) if energy_gross > 0 else ZERO

    return EtsEstimate(
        method=method,
        net=net,
        vat=vat,
        gross=gross,
        rate_gross=rate_gross,
        co2_kg=co2_kg,
        share_of_bill=share_of_bill,
        share_of_energy=share_of_energy,
        percent_gross=percent_gross,
        emission_gross=emission_gross,
    )
