"""GridSecurityAnalyzer — combines three signals into one risk per action.

Attached via `conversation.set_security_analyzer(...)`. For each ActionEvent:

1. the model's own risk label (`security_risk`),
2. escalated one level when the model's self-rated confidence is low
   (`grid.enforcement`),
3. raised to Grid's deterministic rule floor (`grid.rules`) — `rm -rf`,
   `git push`, edits outside the project, secrets, publishing, deploys are RED
   no matter what the model said.

The worst of these wins. Rules and confidence can only raise risk. If anything
in here throws, the action is HIGH (fail closed). The confirmation policy then
does the gating.
"""

from __future__ import annotations

import logging

from openhands.sdk.event.llm_convertible import ActionEvent
from openhands.sdk.security.analyzer import SecurityAnalyzerBase
from openhands.sdk.security.risk import SecurityRisk

from grid.access import granted_roots
from grid.confidence_emit import parse_action_confidence
from grid.enforcement import effective_risk_value
from grid.events import action_info, action_reasoning, action_thought
from grid.rules import READ_ONLY_TOOL_NAMES, classify_action, worse
from grid.tiers import GridTier, risk_value_from_tier, tier_from_risk_value

log = logging.getLogger(__name__)


def assess_full(
    risk_value: str,
    thought: str,
    reasoning: str | None,
    info,
    *,
    workspace: str | None,
    threshold: float,
    strict: bool,
    escalate_on_missing: bool,
    enforce_confidence: bool = True,
    roots: tuple[str, ...] | list[str] = (),
) -> tuple[str, list[str], set[str]]:
    """Pure combination step. Returns (risk value, reasons, RED categories).

    When the result is RED but no deterministic rule made it RED (the model
    labeled it HIGH, or low confidence escalated it), the category is
    "model-flagged"."""
    # The SDK never asks the model to label read-only tools (grep, glob, web_search...), so they
    # arrive UNKNOWN; without this every search would stop for approval.
    if risk_value == "UNKNOWN" and info.tool_name in READ_ONLY_TOOL_NAMES:
        risk_value = "LOW"
    # Grid's own browser profile and Mac control are gated per app/site by Grid itself (and the rules
    # still make sending, buying, deleting and secrets RED), so a model's MEDIUM shouldn't stop every click.
    if risk_value in ("UNKNOWN", "MEDIUM") and (info.tool_name == "computer" or info.tool_name.startswith("browser_")):
        risk_value = "LOW"
    confidence = parse_action_confidence(thought, reasoning) if enforce_confidence else None
    escalated = effective_risk_value(
        risk_value,
        confidence,
        threshold=threshold,
        strict=strict,
        escalate_on_missing=escalate_on_missing and enforce_confidence,
    )
    tier = tier_from_risk_value(escalated)
    reasons: list[str] = []
    if escalated != risk_value:
        reasons.append(f"low confidence: {risk_value} -> {escalated}")
    verdict = classify_action(info, workspace, roots)
    categories = set(verdict.categories)
    if verdict.tier in (GridTier.YELLOW, GridTier.RED):
        tier = worse(tier, verdict.tier)
        reasons.extend(verdict.reasons)
    if tier is GridTier.RED and not categories:
        categories.add("model-flagged")
        if not reasons:
            reasons.append("the model labeled this HIGH risk")
    return risk_value_from_tier(tier), reasons, categories


def assess(risk_value: str, thought: str, reasoning: str | None, info, **kw) -> tuple[str, list[str]]:
    value, reasons, _ = assess_full(risk_value, thought, reasoning, info, **kw)
    return value, reasons


class GridSecurityAnalyzer(SecurityAnalyzerBase):
    """Confidence- and rule-aware risk analyzer."""

    confidence_threshold: float = 0.6
    strict: bool = False
    escalate_on_missing: bool = False
    enforce_confidence: bool = True
    workspace: str | None = None
    chat_id: str | None = None      # for this chat's "allow once" folder grants

    def security_risk(self, action: ActionEvent) -> SecurityRisk:
        try:
            from grid.moderation import get_context
            from grid.safety import action_blocked_reason

            if action_blocked_reason(action, context=get_context(self.chat_id)):
                return SecurityRisk.HIGH
            value, _ = assess(
                _risk_value(action),
                action_thought(action) or "",
                action_reasoning(action),
                action_info(action),
                workspace=self.workspace,
                threshold=self.confidence_threshold,
                strict=self.strict,
                escalate_on_missing=self.escalate_on_missing,
                enforce_confidence=self.enforce_confidence,
                roots=granted_roots(self.chat_id),
            )
            return SecurityRisk(value)
        except Exception:  # fail closed
            log.exception("GridSecurityAnalyzer failed; treating action as HIGH")
            return SecurityRisk.HIGH


def _risk_value(action) -> str:
    """The LLM-predicted risk as a string. Missing risk is UNKNOWN."""
    base = getattr(action, "security_risk", None)
    if base is None:
        return "UNKNOWN"
    raw = getattr(base, "value", base)
    return raw if isinstance(raw, str) else "UNKNOWN"


# Kept for backwards compatibility with earlier tests/imports.
def _thought_body(action) -> str:
    return action_thought(action) or ""


def _reasoning(action) -> str | None:
    return action_reasoning(action)
