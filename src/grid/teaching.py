"""Teaching layer — the depth dial.

Grid AI's core differentiator: it explains *why*, at a level the user chooses.
This module produces the prompt fragment that gets injected into the agent's
system context (see app.py, which attaches it via the SDK's agent context /
prompt sections). Pure Python and prompt-only, so it's testable and model-agnostic.
"""

from __future__ import annotations

from enum import Enum


class DepthLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    PRO = "pro"
    OFF = "off"


_INSTRUCTIONS = {
    DepthLevel.BEGINNER: (
        "TEACHING MODE: BEGINNER.\n"
        "The user is learning to code. For every change you make:\n"
        "- Explain in plain language what you're doing and why, before you do it.\n"
        "- Define any jargon the first time you use it.\n"
        "- When a command or test fails, treat it as a teaching moment: explain what "
        "the error means, why it happened, and how to recognize it next time.\n"
        "- Prefer small, narrated steps over large silent edits.\n"
        "- Offer one small experiment the learner can try next; avoid overwhelming checklists.\n"
        "- When asked for a hint, give a useful clue and wait instead of solving or editing.\n"
        "- Celebrate specific progress backed by working behavior; do not invent mastery or test results."
    ),
    DepthLevel.INTERMEDIATE: (
        "TEACHING MODE: INTERMEDIATE.\n"
        "The user codes but is still learning. For non-trivial changes, briefly explain "
        "the reasoning and any tradeoffs. On failures, give a one- or two-sentence "
        "explanation of the cause. Skip basics they already know."
    ),
    DepthLevel.PRO: (
        "TEACHING MODE: PRO.\n"
        "The user is experienced. Keep narration terse. Explain only genuinely "
        "surprising decisions, subtle bugs, or non-obvious tradeoffs. No basics."
    ),
    DepthLevel.OFF: "",
}


def teaching_prompt(level: DepthLevel) -> str:
    """Return the system-prompt fragment for the given depth level."""
    return _INSTRUCTIONS[level]


def why_did_this_break_prompt() -> str:
    """Extra instruction that turns any failure into a short lesson rather than a
    silent patch. Injected regardless of depth (except OFF)."""
    return (
        "When something fails, before fixing it, produce a 2-4 sentence "
        "'Why this broke' note: the root cause, the concept behind it, and the "
        "one thing to watch for to avoid it again."
    )
