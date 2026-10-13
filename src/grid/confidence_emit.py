"""Confidence-score emission and parsing.

The SDK already asks the LLM to predict a per-action `security_risk` field
(see event/llm_convertible/action.py). Grid AI adds the companion signal the SDK
lacks: a per-action *confidence* the model self-reports in its thought. We:

  1. Instruct the model (system prompt) to end each action's thought with a
     machine-readable line: `CONFIDENCE: <0.0-1.0>`.
  2. Parse that value out of the ActionEvent thought text (pure, tested here).
  3. Feed it through the existing ConfidenceGate to get an effective tier +
     a human badge.

Parsing is pure string work (no SDK import) so it's fully unit-tested; app.py
does the thin job of pulling the thought text off the SDK event.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from grid.confidence import ConfidenceGate
from grid.tiers import GridTier

CONFIDENCE_INSTRUCTION = (
    "CONFIDENCE REPORTING: Before every tool action, end your thought with a "
    "line exactly of the form:\n"
    "    CONFIDENCE: <value>\n"
    "where <value> is a number from 0.0 to 1.0 giving your honest confidence "
    "that this specific action is correct and safe. Use high values (>0.85) only "
    "when you are sure; use low values (<0.6) when you are guessing or "
    "experimenting. Be calibrated: it is better to admit uncertainty than to "
    "overstate confidence."
)

# A reported score is a whole line: "CONFIDENCE: 0.82". This is what the
# system prompt asks for, and it wins over any other shape in the same text.
_REPORT_RE = re.compile(
    r"^[ \t]*confidence[ \t]*:[ \t]*(\d+(?:\.\d+)?)[ \t]*(%?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
# A whole line "confidence = 0.82" is accepted when the model didn't use the
# colon form. It does not override a CONFIDENCE: line.
_ASSIGN_LINE_RE = re.compile(
    r"^[ \t]*confidence[ \t]*=[ \t]*(\d+(?:\.\d+)?)[ \t]*(%?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
# Last resort, for a score buried in a sentence. Used only when neither line
# pattern matches, so `confidence = 0.05` inside code cannot override a report.
_LOOSE_RE = re.compile(
    r"confidence[ \t]*[:=][ \t]*(\d+(?:\.\d+)?)[ \t]*(%?)",
    re.IGNORECASE,
)


def _to_unit(raw: str, pct: str) -> float:
    value = float(raw)
    if pct:
        value /= 100.0
    elif value > 1.0 and "." not in raw:
        # A bare integer > 1 (e.g. "95") is a percentage. A decimal > 1
        # (e.g. "1.4") is a malformed fraction and is clamped below.
        value /= 100.0
    return max(0.0, min(1.0, value))


def _last_match(pattern: re.Pattern[str], text: str) -> float | None:
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    raw, pct = matches[-1].groups()
    return _to_unit(raw, pct)


def parse_confidence(text: str) -> float | None:
    """Extract a confidence value in [0.0, 1.0] from text, or None.

    A `CONFIDENCE:` line wins over a `confidence =` line, which wins over a
    number mentioned in passing. When several reports of the same kind appear,
    the last one wins (models sometimes restate the score)."""
    if not text:
        return None
    reported = _last_match(_REPORT_RE, text)
    if reported is not None:
        return reported
    assigned = _last_match(_ASSIGN_LINE_RE, text)
    if assigned is not None:
        return assigned
    return _last_match(_LOOSE_RE, text)


def parse_action_confidence(thought: str | None, reasoning: str | None = None) -> float | None:
    """Confidence for one action. The thought's score wins over reasoning.

    Reasoning is only consulted when the thought itself has no score, so a
    snippet of code in the reasoning (`confidence = 0.99`) cannot wave a
    low-confidence action through."""
    if thought:
        score = parse_confidence(thought)
        if score is not None:
            return score
    if reasoning:
        return parse_confidence(reasoning)
    return None


@dataclass(frozen=True)
class ConfidenceReading:
    score: float
    label: str
    base_tier: GridTier
    effective_tier: GridTier

    @property
    def downgraded(self) -> bool:
        return self.effective_tier is not self.base_tier


def read_confidence(
    text: str,
    base_tier: GridTier,
    gate: ConfidenceGate | None = None,
    reasoning: str | None = None,
) -> ConfidenceReading | None:
    """Parse confidence from `text` and combine it with `base_tier` via the gate.

    `reasoning` is a fallback used only when `text` (the thought) has no score.
    Returns None if no confidence value is present (caller decides the default —
    typically treat a missing score as low/unknown and stay cautious)."""
    gate = gate or ConfidenceGate()
    score = parse_action_confidence(text, reasoning)
    if score is None:
        return None
    return ConfidenceReading(
        score=score,
        label=gate.label(score),
        base_tier=base_tier,
        effective_tier=gate.adjust(base_tier, score),
    )
