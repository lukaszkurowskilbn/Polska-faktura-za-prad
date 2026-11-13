"""Opłata mocowa dla gospodarstw domowych — wybór segmentu wg zużycia rocznego.

Dla gospodarstw domowych opłata mocowa jest RYCZAŁTOWA i zależy od rocznego
zużycia energii w punkcie poboru (4 segmenty). Stawki ustala URE co roku.

Stawki 2026 (Informacja Prezesa URE nr 58/2025 z 30.10.2025, netto zł/mc):
    seg.1  ≤ 500 kWh/rok ............ 4,29
    seg.2  > 500 do 1200 ............ 10,31
    seg.3  > 1200 do 2800 ........... 17,18
    seg.4  > 2800 .................. 24,05   (zgodne z fakturą „seg.4")

Progi i stawki są parametrami (zmieniają się rok do roku) — warstwa HA podaje je
jako edytowalne pola. Tu trzymamy tylko czystą logikę wyboru.
"""

from __future__ import annotations

from decimal import Decimal

from .models import _dec

# Górne granice segmentów [kWh/rok]. Ostatni segment jest bez górnej granicy.
SEGMENT_THRESHOLDS: tuple[int, int, int] = (500, 1200, 2800)

# Domyślne stawki 2026 [zł/mc netto] — wartości startowe edytowalnych pól.
DEFAULT_SEGMENT_RATES_2026: tuple[str, str, str, str] = (
    "4.29",
    "10.31",
    "17.18",
    "24.05",
)


def segment_for(annual_kwh: Decimal | float | int) -> int:
    """Numer segmentu (1..4) dla rocznego zużycia [kWh]."""
    kwh = _dec(annual_kwh)
    if kwh <= SEGMENT_THRESHOLDS[0]:
        return 1
    if kwh <= SEGMENT_THRESHOLDS[1]:
        return 2
    if kwh <= SEGMENT_THRESHOLDS[2]:
        return 3
    return 4


def rate_for(
    annual_kwh: Decimal | float | int,
    rates: tuple[Decimal | str | float, Decimal | str | float,
                 Decimal | str | float, Decimal | str | float],
) -> Decimal:
    """Stawka opłaty mocowej [zł/mc] dla rocznego zużycia i 4 stawek segmentów."""
    seg = segment_for(annual_kwh)
    return _dec(rates[seg - 1])
