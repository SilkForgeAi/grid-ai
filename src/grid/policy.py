"""GridConfirmationPolicy — the Green/Yellow/Red autonomy gate.

This is the one place Grid AI touches the SDK's security model. It subclasses the
SDK's ConfirmationPolicyBase so it drops straight into
`conversation.set_confirmation_policy(...)`, and it expresses Grid AI's tiers on
top of the SDK's SecurityRisk levels:

    LOW    (GREEN)   -> run freely            -> should_confirm = False
    MEDIUM (YELLOW)  -> soft confirm          -> should_confirm = confirm_yellow
    HIGH   (RED)     -> always stop and ask   -> should_confirm = True
    UNKNOWN          -> conservative          -> should_confirm = confirm_unknown

RED is unconditional: no confidence score or config can make a HIGH-risk action
auto-run. That invariant is the whole safety story (ROADMAP §4/§5).
"""

from __future__ import annotations

from openhands.sdk.security.confirmation_policy import ConfirmationPolicyBase
from openhands.sdk.security.risk import SecurityRisk

from grid.tiers import should_confirm_for_risk_value


class GridConfirmationPolicy(ConfirmationPolicyBase):
    """Grid AI's risk-tiered confirmation policy.

    A thin adapter: it hands the SDK's SecurityRisk to the pure decision function
    in `grid.tiers` (which is unit-tested without the SDK). Fields are
    pydantic-validated via the SDK base; defaults match GridConfig.
    """

    confirm_yellow: bool = True
    confirm_unknown: bool = True

    def should_confirm(self, risk: SecurityRisk = SecurityRisk.UNKNOWN) -> bool:
        # `risk` is a SecurityRisk enum in current SDKs. A bare string (or some
        # future type) still has to reach the gate instead of raising AttributeError.
        raw = getattr(risk, "value", risk)
        risk_value = raw if isinstance(raw, str) else "UNKNOWN"
        return should_confirm_for_risk_value(
            risk_value,
            confirm_yellow=self.confirm_yellow,
            confirm_unknown=self.confirm_unknown,
        )
