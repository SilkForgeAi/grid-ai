"""Test-regression detector.

The SDK's StuckDetector catches repetition, but not the case ROADMAP §4 calls
out: a change that makes things *worse* (test pass-rate drops). Grid AI adds a
lightweight detector that watches test results over time and flags a regression
so the session can revert to the last good checkpoint instead of digging deeper.

Pure Python: it parses a pytest-style summary line and tracks pass ratios. It's
wired into the live agent as an observer over the SDK event stream (see app.py),
but the logic here has no SDK dependency so it can be unit-tested directly.

A regression is any of:

- the pass ratio dropped, or the number of failing tests rose, against the last
  run of comparable scope (a one-file run is not compared to a full suite, and
  it does not become the baseline for the next full suite)
- fewer tests actually executed (failures silenced with skip / xfail / deselect)
- the suite stopped running entirely (collection error, "no tests ran")

An empty run has no pass ratio. It is not treated as 100% and is not a baseline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A pytest summary is a line of "<n> <outcome>" clauses, optionally wrapped in
# "===" and optionally ending in "in 0.12s". Outcomes pytest actually prints:
# passed, failed, error(s), skipped, deselected, xfailed, xpassed.
# warnings and reruns are noise on that same line and are ignored.
_COUNT_RE = re.compile(
    r"(\d+)\s+(xfailed|xpassed|passed|failed|errors?|skipped|deselected)\b",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(r"\d+\s+(?:warnings?|reruns?)\b", re.IGNORECASE)
_IN_TIME_RE = re.compile(r"\bin\s+\d+(?:\.\d+)?s\b", re.IGNORECASE)
_COLLECTED_RE = re.compile(
    r"collected\s+(\d+)\s+items?\b(?!\s*/)",
    re.IGNORECASE,
)
_COLLECTED_ERROR_RE = re.compile(
    r"collected\s+\d+\s+items?\s*/\s*\d+\s+errors?\b",
    re.IGNORECASE,
)

# Two runs are the same suite when their scope counts match, or differ by at
# most the larger of 2 tests and 10% of the bigger run. Anything wider (a
# single file after a full suite, or the reverse) is a different scope.
_SCOPE_ABS_SLACK = 2
_SCOPE_REL_DENOM = 10


@dataclass(frozen=True)
class RunResult:
    """Outcome of a single test run. (Named RunResult rather than TestResult so
    pytest doesn't try to collect it as a test case.)"""

    passed: int
    failed: int
    skipped: int = 0
    deselected: int = 0
    # pytest's "collected N items" line, when the output included one.
    # None means the output didn't say, and scope falls back to the counts above.
    collected: int | None = None
    # True when the suite didn't produce a summary at all: collection error,
    # "no tests ran", missing path, INTERNALERROR.
    errored: bool = False

    @property
    def executed(self) -> int:
        """Tests that ran to a pass or a fail. Skips and deselection don't count."""
        return self.passed + self.failed

    @property
    def total(self) -> int:
        """Tests this result accounts for: ran, skipped, or deselected."""
        return self.passed + self.failed + self.skipped + self.deselected

    @property
    def scope(self) -> int:
        """How big a suite this run was. Used to decide whether two runs are
        comparable. The explicit collected count wins when we have it."""
        if self.collected is not None:
            return self.collected
        return self.total

    @property
    def pass_ratio(self) -> float | None:
        """Fraction of executed tests that passed. None when nothing ran —
        an empty run is not a perfect score."""
        if self.executed == 0:
            return None
        return self.passed / self.executed


def _summary_counts(line: str) -> dict[str, int] | None:
    """Parse one physical line. Returns outcome counts only when the line is a
    pytest summary and nothing else — prose that merely mentions "12 passed"
    returns None."""
    core = line.strip()
    core = re.sub(r"^=+\s*", "", core)
    core = re.sub(r"\s*=+\s*$", "", core).strip()
    if not core:
        return None
    cleaned = _NOISE_RE.sub(" ", core)
    if not _COUNT_RE.search(cleaned):
        return None
    remainder = _COUNT_RE.sub(" ", cleaned)
    remainder = _IN_TIME_RE.sub(" ", remainder)
    remainder = re.sub(r"[, ]+", " ", remainder).strip()
    if remainder:
        return None
    counts: dict[str, int] = {}
    for match in _COUNT_RE.finditer(cleaned):
        number = int(match.group(1))
        word = match.group(2).lower()
        key = "error" if word.startswith("error") else word
        counts[key] = counts.get(key, 0) + number
    return counts


def _last_summary_counts(text: str) -> dict[str, int] | None:
    """Last summary line wins. A traceback earlier in the output
    ("assert 1 passed == 2") must not beat the real footer."""
    found: dict[str, int] | None = None
    for line in text.splitlines():
        counts = _summary_counts(line)
        if counts is not None:
            found = counts
    return found


def _collected_count(text: str) -> int | None:
    found: int | None = None
    for line in text.splitlines():
        match = _COLLECTED_RE.search(line.strip())
        if match:
            found = int(match.group(1))
    return found


def _is_dead_run(text: str) -> bool:
    """True when pytest never produced a result: nothing collected, the path
    was missing, or pytest crashed."""
    for line in text.splitlines():
        body = line.strip()
        body = re.sub(r"^=+\s*", "", body)
        body = re.sub(r"\s*=+\s*$", "", body).strip()
        lowered = body.lower()
        if lowered.startswith("no tests ran"):
            return True
        if re.match(r"collected\s+0\s+items?\b", lowered):
            return True
        if _COLLECTED_ERROR_RE.match(lowered):
            return True
        if body.startswith("ERROR: file or directory not found:"):
            return True
        if body.startswith("INTERNALERROR>"):
            return True
    return False


def parse_pytest_summary(text: str) -> RunResult | None:
    """Extract a RunResult from pytest output.

    Returns None when the text has neither a summary line nor a recognized
    "suite didn't run" failure. A collection failure is returned as an errored
    result with nothing executed, so the detector can flag it.
    """
    counts = _last_summary_counts(text)
    if counts is not None:
        # xpassed ran and passed. xfailed is a silenced failure — same idea as
        # a skip, so it counts as not executed.
        return RunResult(
            passed=counts.get("passed", 0) + counts.get("xpassed", 0),
            failed=counts.get("failed", 0) + counts.get("error", 0),
            skipped=counts.get("skipped", 0) + counts.get("xfailed", 0),
            deselected=counts.get("deselected", 0),
            collected=_collected_count(text),
        )
    if _is_dead_run(text):
        return RunResult(passed=0, failed=0, collected=0, errored=True)
    return None


def _scopes_comparable(prev: RunResult, curr: RunResult) -> bool:
    lo, hi = sorted((prev.scope, curr.scope))
    if lo == 0:
        return False
    return (hi - lo) <= max(_SCOPE_ABS_SLACK, hi // _SCOPE_REL_DENOM)


def _fmt(result: RunResult) -> str:
    parts = [f"{result.passed} passed", f"{result.failed} failed"]
    if result.skipped:
        parts.append(f"{result.skipped} skipped")
    if result.deselected:
        parts.append(f"{result.deselected} deselected")
    return ", ".join(parts)


@dataclass
class RegressionDetector:
    """Tracks test results and reports regressions against the last comparable run."""

    history: list[RunResult] = field(default_factory=list)

    def record(self, result: RunResult) -> None:
        self.history.append(result)

    def record_from_output(self, text: str) -> RunResult | None:
        result = parse_pytest_summary(text)
        if result is not None:
            self.record(result)
        return result

    @property
    def latest(self) -> RunResult | None:
        return self.history[-1] if self.history else None

    def _baseline(self) -> RunResult | None:
        """Last earlier run of the same scope that actually executed tests.

        Walks back past narrower runs and past empty runs, so a one-file run
        in the middle of the history can't become the baseline.
        """
        if len(self.history) < 2:
            return None
        curr = self.history[-1]
        for prev in reversed(self.history[:-1]):
            if prev.errored or prev.executed == 0:
                continue
            if _scopes_comparable(prev, curr):
                return prev
        return None

    def is_regression(self) -> bool:
        if not self.history:
            return False
        curr = self.history[-1]
        if curr.errored:
            return any((not run.errored) and run.executed > 0 for run in self.history[:-1])
        prev = self._baseline()
        if prev is None:
            return False
        if curr.executed < prev.executed:
            return True
        if curr.failed > prev.failed:
            return True
        prev_ratio, curr_ratio = prev.pass_ratio, curr.pass_ratio
        if prev_ratio is None or curr_ratio is None:
            return False
        return curr_ratio < prev_ratio

    def reason(self) -> str | None:
        if not self.is_regression():
            return None
        curr = self.history[-1]
        if curr.errored:
            return (
                "Regression: the test suite stopped running "
                "(nothing collected, or the run errored before a summary)."
            )
        prev = self._baseline()
        assert prev is not None
        if curr.executed < prev.executed:
            return (
                f"Regression: tests executed dropped {prev.executed} -> {curr.executed} "
                f"({_fmt(prev)} -> {_fmt(curr)})."
            )
        if curr.failed > prev.failed:
            return (
                f"Regression: failing tests increased {prev.failed} -> {curr.failed} "
                f"({_fmt(prev)} -> {_fmt(curr)})."
            )
        assert prev.pass_ratio is not None and curr.pass_ratio is not None
        return (
            f"Regression: pass ratio {prev.pass_ratio:.0%} -> {curr.pass_ratio:.0%} "
            f"({prev.passed}/{prev.executed} -> {curr.passed}/{curr.executed})."
        )
