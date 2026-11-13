"""Rdzeń kalkulatora rachunku — niezależny od Home Assistant."""

from .calculator import Bill, LineItem, calculate, round_pln
from .ets import EtsEstimate, EtsMethod, EtsParams, estimate as estimate_ets
from .power_fee import (
    DEFAULT_SEGMENT_RATES_2026,
    SEGMENT_THRESHOLDS,
    rate_for as power_fee_rate_for,
    segment_for as power_fee_segment_for,
)
from .models import (
    BillingPeriod,
    Consumption,
    Group,
    TariffPosition,
    TariffProfile,
    Unit,
    Zone,
)
from .profiles import ProfileError, load_builtin_profiles, load_profile_file

__all__ = [
    "Bill",
    "LineItem",
    "calculate",
    "round_pln",
    "EtsEstimate",
    "EtsMethod",
    "EtsParams",
    "estimate_ets",
    "power_fee_rate_for",
    "power_fee_segment_for",
    "SEGMENT_THRESHOLDS",
    "DEFAULT_SEGMENT_RATES_2026",
    "BillingPeriod",
    "Consumption",
    "Group",
    "TariffPosition",
    "TariffProfile",
    "Unit",
    "Zone",
    "ProfileError",
    "load_builtin_profiles",
    "load_profile_file",
]
