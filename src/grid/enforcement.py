"""Confidence enforcement — the pure logic that turns a self-rated confidence
into an *effective* risk level.

Enforcement (as opposed to the observe-only badge in confidence_emit) works by
escalating risk when the model is unsure: a low-confidence LOW action becomes
MEDIUM, a low-confidence MEDIUM becomes HIGH (only under `strict`). Because the
SDK's confirmation flow already keys off risk, escalating the risk *is* the
enforcement — no stateful hooks, no callback-ordering assumptions. `analyzer.py`
wraps this in an SDK SecurityAnalyzer.

Kept SDK-free and fully unit-tested; the analyzer is a thin adapter over it.
"""

from __future__ import annotations

import warnings

from grid.confidence import ConfidenceGate
from grid.tiers import GridTier, risk_value_from_tier, tier_from_risk_value


def effective_risk_value(
    base_risk_value: str,
    confidence: float | None,
    threshold: float = 0.6,
    strict: bool = False,
    escalate_on_missing: bool = False,
) -> str:
    """Return the effective SecurityRisk value string after applying confidence.

    Args:
        base_risk_value: the LLM-predicted risk ("LOW"/"MEDIUM"/"HIGH"/"UNKNOWN").
        confidence: parsed self-rated confidence in [0,1], or None if absent.
        threshold: confidence below this is "low".
        strict: if True, a low-confidence MEDIUM escalates to HIGH.
        escalate_on_missing: if True, a missing score nudges LOW -> MEDIUM so an
            unreported action is at least soft-confirmed. Defaults to False to
            avoid friction on every un-scored action.

    Escalation never *lowers* risk. HIGH stays HIGH. UNKNOWN stays UNKNOWN
    (the confirmation policy's confirm_unknown handles that case).

    An unrecognized base_risk_value does not raise. It comes back as HIGH, so a
    risk level this code has never seen cannot auto-run and cannot be softened
    by a high confidence score.
    """
    try:
        base_tier = tier_from_risk_value(base_risk_value)
    except ValueError:
        warnings.warn(
            f"Unrecognized SecurityRisk value {base_risk_value!r}; escalating to HIGH.",
            UserWarning,
            stacklevel=2,
        )
        return risk_value_from_tier(GridTier.RED)

    if confidence is None:
        if escalate_on_missing and base_tier is GridTier.GREEN:
            return risk_value_from_tier(GridTier.YELLOW)
        return risk_value_from_tier(base_tier)

    effective_tier = ConfidenceGate(threshold=threshold, strict=strict).adjust(
        base_tier, confidence
    )
    return risk_value_from_tier(effective_tier)
