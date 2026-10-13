"""Autonomous mode: the user approves up front, Grid stops asking.

What autonomous mode runs without a prompt:
  GREEN and YELLOW actions; RED actions only when every RED category
  they hit was pre-approved with --allow (e.g. --allow push).

What it never runs unattended (a human can still approve these one at a time
in a normal session): root, disk writes, credentials, writes outside the
project, system services, .git internals, and anything unclassified.

What autonomous mode never relaxes: verification. A task is only "verified"
when Grid itself ran a real check and it passed.

Pure Python, no SDK import.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from grid.rules import ALLOWABLE_RED, HARD_BLOCKED_RED
from grid.tiers import GridTier


def parse_allow(values: list[str] | tuple[str, ...] | None) -> frozenset[str]:
    """Validate --allow values. Accepts repeated flags or comma lists."""
    names: set[str] = set()
    for value in values or ():
        for name in value.split(","):
            name = name.strip().lower()
            if not name:
                continue
            if name in HARD_BLOCKED_RED:
                raise ValueError(
                    f"'{name}' ({HARD_BLOCKED_RED[name]}) can never be pre-approved; "
                    "it always needs a human at the prompt."
                )
            if name not in ALLOWABLE_RED:
                raise ValueError(
                    f"unknown category '{name}'. Choose from: {', '.join(sorted(ALLOWABLE_RED))}"
                )
            names.add(name)
    return frozenset(names)


@dataclass(frozen=True)
class PendingItem:
    description: str
    tier: GridTier
    categories: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class AutonomyPolicy:
    allow: frozenset[str] = frozenset()

    def blocked(self, item: PendingItem) -> list[str]:
        """Why this item can't run unattended ([] means it can)."""
        if item.tier is GridTier.UNKNOWN:
            return ["unknown action: needs human review (never unattended)"]
        if item.tier is not GridTier.RED:
            return []
        cats = item.categories or frozenset({"model-flagged"})
        out = []
        for c in sorted(cats):
            if c in HARD_BLOCKED_RED:
                out.append(f"{c}: {HARD_BLOCKED_RED[c]} (never unattended)")
            elif c not in self.allow:
                out.append(f"{c}: {ALLOWABLE_RED.get(c, c)} (not pre-approved; --allow {c})")
        return out

    def decide(self, items: list[PendingItem]) -> tuple[bool, list[str]]:
        """(approve all?, messages for the blocked ones). The SDK approves or
        rejects a batch together, so one blocked item rejects the batch."""
        messages = []
        for item in items:
            why = self.blocked(item)
            if why:
                messages.append(f"{item.description} -> " + "; ".join(why))
        return (not messages, messages)


def describe_mode(allow: frozenset[str], max_steps: int | None = None, review: bool = True) -> str:
    lines = [
        "AUTONOMOUS MODE - Grid will not ask before acting.",
        "  runs freely : GREEN and YELLOW actions",
        "  RED allowed : " + (", ".join(sorted(allow)) if allow else "none (RED actions are refused, the agent is told why)"),
        "  never       : unknown actions, " + ", ".join(sorted(HARD_BLOCKED_RED)),
        "  always      : every change is checkpointed; regressions are reverted;",
        "                'done' only counts after Grid runs a real check and it passes.",
    ]
    if review:
        lines.append("  review     : before 'done' the agent re-reads its changes for consistency.")
    if max_steps:
        lines.append(f"  step limit : pauses after {max_steps} steps on one task (change it in Settings).")
    return "\n".join(lines)
