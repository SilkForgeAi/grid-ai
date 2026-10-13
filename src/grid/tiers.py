"""Grid AI autonomy tiers, mapped onto the SDK's SecurityRisk levels.

The SDK speaks LOW / MEDIUM / HIGH / UNKNOWN (`openhands.sdk.security.risk`).
Grid AI's product language is GREEN / YELLOW / RED. This module is the single
source of truth for that mapping and is deliberately pure Python (no SDK import)
so the tier logic is testable in isolation. `policy.py` is where these tiers meet
the SDK's ConfirmationPolicy.

    LOW     -> GREEN   run freely, no confirmation
    MEDIUM  -> YELLOW  soft confirm (batchable)
    HIGH    -> RED     always stop and ask (never auto-run, regardless of confidence)
    UNKNOWN -> UNKNOWN treat conservatively (configurable)
"""

from __future__ import annotations

import warnings
from enum import Enum


class GridTier(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    UNKNOWN = "UNKNOWN"

    @property
    def color(self) -> str:
        return {
            GridTier.GREEN: "green",
            GridTier.YELLOW: "yellow",
            GridTier.RED: "red",
            GridTier.UNKNOWN: "white",
        }[self]


# Mapping keyed by the SDK SecurityRisk *string value* so this module never has
# to import the SDK. SecurityRisk is a `str` Enum, so `risk.value` yields these.
_RISK_VALUE_TO_TIER = {
    "LOW": GridTier.GREEN,
    "MEDIUM": GridTier.YELLOW,
    "HIGH": GridTier.RED,
    "UNKNOWN": GridTier.UNKNOWN,
}

_TIER_TO_RISK_VALUE = {
    GridTier.GREEN: "LOW",
    GridTier.YELLOW: "MEDIUM",
    GridTier.RED: "HIGH",
    GridTier.UNKNOWN: "UNKNOWN",
}


def tier_from_risk_value(risk_value: str) -> GridTier:
    """Map an SDK SecurityRisk value string to a Grid tier.

    Raises ValueError for a value this module doesn't know. Callers that decide
    whether an action runs should not use this directly — `should_confirm_for_risk_value`
    and `effective_risk_value` fail closed on an unrecognized value instead of raising.
    """
    try:
        return _RISK_VALUE_TO_TIER[risk_value]
    except KeyError as exc:
        raise ValueError(f"Unknown SecurityRisk value: {risk_value!r}") from exc


def risk_value_from_tier(tier: GridTier) -> str:
    """Map a Grid tier back to an SDK SecurityRisk value string."""
    return _TIER_TO_RISK_VALUE[tier]


def should_confirm_for_risk_value(
    risk_value: str,
    confirm_yellow: bool = True,
    confirm_unknown: bool = True,
) -> bool:
    """Pure Green/Yellow/Red confirmation decision, keyed by SecurityRisk value.

    This is the actual policy logic, kept SDK-free so it's testable in isolation.
    `GridConfirmationPolicy.should_confirm` is a thin adapter over this.

        HIGH  (RED)     -> always confirm (unconditional safety invariant)
        MEDIUM(YELLOW)  -> confirm iff confirm_yellow
        LOW   (GREEN)   -> never confirm
        UNKNOWN         -> confirm iff confirm_unknown
        anything else   -> always confirm (a risk level we don't know must stop)
    """
    try:
        tier = tier_from_risk_value(risk_value)
    except ValueError:
        warnings.warn(
            f"Unrecognized SecurityRisk value {risk_value!r}; confirming.",
            UserWarning,
            stacklevel=2,
        )
        return True
    if tier is GridTier.RED:
        return True
    if tier is GridTier.YELLOW:
        return confirm_yellow
    if tier is GridTier.GREEN:
        return False
    return confirm_unknown
