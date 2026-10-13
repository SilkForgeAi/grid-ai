"""Lesson mode: Grid teaches step by step instead of doing it for you.

    /learn <topic>   start a lesson: a plan, a starter file with TODOs and a test
    /hint            a nudge for the current step (not the answer)
    /check           run my work against the step's test and explain the result
    /next            on to the next step
    /solution        show and explain a correct solution for this step
    /quiz [topic]    a few quick questions to check it stuck

Lesson tasks run with verification and regression-revert off: a lesson's test
is *supposed* to fail until the learner solves it, and Grid must not "fix" that.
"""

from __future__ import annotations

from dataclasses import dataclass

LESSON_RULES = (
    "LESSON MODE. You are teaching, not doing. The person writes the solution; you explain, set up the exercise, "
    "check their work and give hints. Keep each message short and end with exactly what they should do next."
)

_TEMPLATES = {
    "learn": (
        "{rules}\nTeach me: {arg}.\n"
        "1. Pick a sensible starting point for an adult beginner-to-intermediate (ask one quick question first only if "
        "it really changes the lesson).\n"
        "2. Create lessons/<short-slug-for-the-topic>/ with: README.md (the plan: 3-6 small steps, one line each, step 1 "
        "marked current), a starter file for step 1 with clear TODO comments for me to fill in, and a test for step 1 "
        "that passes only when it's done right. Use this project's language, or Python if there isn't an obvious one.\n"
        "3. Explain the idea behind step 1 in plain language with a tiny example that is NOT the solution.\n"
        "4. Stop. Tell me which file to open and to type /check when I'm ready (or /hint if I'm stuck).\n"
        "Do NOT solve the exercise. Its test is meant to fail until I do."
    ),
    "check": (
        "{rules}\nCheck my work on the current lesson step{arg_suffix}. Run that step's test. Tell me what passed, what "
        "failed and why, in plain words, pointing at the line. If it's wrong, give a hint - do not fix my code. If it "
        "passes, say so (celebrate a little) and tell me to type /next."
    ),
    "hint": (
        "{rules}\nGive me one hint for the current lesson step{arg_suffix}: a nudge in the right direction, not the "
        "answer and not code I can paste. If I've had hints already, make this one more specific. Don't edit files."
    ),
    "next": (
        "{rules}\nI'm done with this step. Mark it done in the lesson README, create the next step's starter file "
        "(with TODOs) and its test, explain the new idea briefly with a tiny example that isn't the solution, then "
        "stop and tell me to try it. If that was the last step, wrap up: what I learned, and one idea to practice on "
        "my own. Don't solve anything."
    ),
    "solution": (
        "{rules}\nShow me a correct solution for the current lesson step{arg_suffix}: write it into the step's file, "
        "run the step's test to show it passes, then walk through it line by line - why each part is there and the "
        "mistake people usually make. Then ask if I want to try a variation or move on with /next."
    ),
    "quiz": (
        "{rules}\nQuiz me with 3 short questions about {arg_or_recent}, one at a time. Wait for my answer each time, "
        "then tell me if I'm right and why before the next one. Don't touch any files."
    ),
}


@dataclass(frozen=True)
class LessonCommand:
    name: str
    usage: str
    description: str


COMMANDS = [
    LessonCommand("learn", "/learn <topic>", "start a step-by-step lesson (you write the code)"),
    LessonCommand("hint", "/hint", "a nudge for the current step - not the answer"),
    LessonCommand("check", "/check", "test your work on this step and explain the result"),
    LessonCommand("next", "/next", "move on to the next step"),
    LessonCommand("solution", "/solution", "show and explain a solution for this step"),
    LessonCommand("quiz", "/quiz [topic]", "three quick questions to check it stuck"),
]
NAMES = {c.name for c in COMMANDS}


def expand_lesson(text: str) -> str | None:
    """The full instruction for a lesson command, or None if `text` isn't one."""
    t = (text or "").strip()
    if not t.startswith("/"):
        return None
    word, _, arg = t[1:].partition(" ")
    word = word.lower()
    if word not in NAMES:
        return None
    arg = arg.strip()
    if word == "learn" and not arg:
        arg = "something useful to start with - suggest three options and let me pick"
    return _TEMPLATES[word].format(
        rules=LESSON_RULES,
        arg=arg,
        arg_suffix=f" ({arg})" if arg else "",
        arg_or_recent=arg or "what we just covered",
    )
