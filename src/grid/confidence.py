"""Per-action confidence signal + tier downgrade.

The SDK has no built-in notion of "how sure is the model about this action."
Grid AI adds one: the agent self-rates each proposed action 0.0-1.0, and if that
confidence is below a threshold we *downgrade* the action's autonomy tier so the
user is asked first ("I'm guessing here, watch me"). This is the cheap,
high-trust signal from ROADMAP §4.

Rules:
  - Low confidence can only make an action *more* cautious, never less.
  - RED stays RED no matter how confident the model is (risk beats confidence).
  - A low-confidence GREEN becomes YELLOW (ask first).
  - A low-confidence YELLOW becomes RED (hard stop) if `strict` is set.
"""

from __future__ import annotations

from dataclasses import dataclass

from grid.tiers import GridTier


@dataclass(frozen=True)
class ConfidenceGate:
    threshold: float = 0.6
    strict: bool = False  # if True, low-confidence YELLOW escalates to RED

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold must be in [0.0, 1.0]")

    def is_low(self, confidence: float) -> bool:
        return confidence < self.threshold

    def label(self, confidence: float) -> str:
        """Human-facing badge text for the UI."""
        if confidence >= 0.85:
            return f"{round(confidence * 100)}% sure"
        if confidence >= self.threshold:
            return f"~{round(confidence * 100)}% — fairly sure"
        return f"{round(confidence * 100)}% — guessing, watch me"

    def adjust(self, tier: GridTier, confidence: float) -> GridTier:
        """Return the effective tier after applying the confidence signal."""
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0.0, 1.0]")

        # Risk always wins: a RED action is never softened by confidence, and a
        # confident model never downgrades RED.
        if tier is GridTier.RED:
            return GridTier.RED

        if not self.is_low(confidence):
            return tier

        # Low confidence -> one step more cautious.
        if tier is GridTier.GREEN:
            return GridTier.YELLOW
        if tier is GridTier.YELLOW:
            return GridTier.RED if self.strict else GridTier.YELLOW
        # UNKNOWN is already conservative.
        return tier
