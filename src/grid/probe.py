"""`grid models test`: does this model actually work with Grid?

Runs a real, small Grid task (a one-line bug with a failing test) in a
throwaway folder, unattended, and measures what Grid's safety layer depends on:
tool calls, per-action risk labels, confidence lines, finishing, and a verified
pass. Costs a few cents on a cloud model; free on a local one.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

from grid.confidence_emit import parse_action_confidence
from grid.config import GridConfig
from grid.events import action_info, action_reasoning, action_thought, is_action
from grid.models import ModelProfile, ProbeResult, build_llm_from_profile, check_endpoint

PROBE_TASK = (
    "The test in this folder fails. Find the bug in calc.py, fix it, run the test to confirm it passes, "
    "then finish with a one-line summary."
)


def _write_probe_project(ws: Path) -> None:
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    # Standard-library unittest: the installed app's engine has no pytest, so a pytest check
    # here could never pass and every model looked "not verified".
    (ws / "test_calc.py").write_text(
        "import unittest\n\nfrom calc import add\n\n\n"
        "class TestAdd(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
    )


def run_probe(profile: ModelProfile, *, llm=None, say=print, max_steps: int = 15) -> ProbeResult:
    """Run the probe. `llm` overrides the profile's model (tests pass a scripted one)."""
    from grid.session import UI, GridSession, Outcome

    result = ProbeResult()
    if llm is None:
        problem = check_endpoint(profile)
        if problem:
            result.error = problem
            return result
    tmp = Path(tempfile.mkdtemp(prefix="grid-probe-"))
    ws = tmp / "probe"
    ws.mkdir()
    _write_probe_project(ws)
    config = GridConfig(
        condense_context=False, load_user_skills=False, load_project_skills=False,
        verify_command=f"{sys.executable} -m unittest -q",
        soft_step_budget=max_steps, headless_max_budgets=1, max_verify_attempts=1, self_review=False,
        confirm_yellow=False, checkpoints=True,
    )
    lines: list[str] = []
    start = time.monotonic()
    session = None
    try:
        model = llm or build_llm_from_profile(profile, usage_id="grid-probe", num_retries=1)
        session = GridSession(str(ws), config, UI(say=lines.append, interactive=False),
                              llm=model, persist=False, visualizer=None)
        report = session.submit(PROBE_TASK)
        result.finished = report.outcome in (Outcome.VERIFIED, Outcome.DONE, Outcome.UNVERIFIED)
        result.verified = report.outcome is Outcome.VERIFIED
        _score_events(session.conversation.state.events, result)
        result.cost = _cost(session)
        if report.outcome is Outcome.ERROR:
            result.error = report.message[:300]
    except Exception as exc:  # bad key, unreachable server, unknown model...
        result.error = f"{type(exc).__name__}: {str(exc)[:300]}"
    finally:
        result.seconds = round(time.monotonic() - start, 1)
        if session is not None:
            session.close()
        shutil.rmtree(tmp, ignore_errors=True)
    return result


def _score_events(events, result: ProbeResult) -> None:
    labeled = confident = 0
    for e in events:
        if not is_action(e):
            continue
        tool = action_info(e).tool_name
        if tool in ("finish", "think", ""):
            continue
        result.actions += 1
        result.tool_calls = True
        risk = getattr(getattr(e, "security_risk", None), "value", None)
        if risk and risk != "UNKNOWN":
            labeled += 1
        if parse_action_confidence(action_thought(e) or "", action_reasoning(e)) is not None:
            confident += 1
    if result.actions:
        result.risk_labeled = labeled / result.actions
        result.confidence = confident / result.actions


def _cost(session) -> float | None:
    try:
        stats = session.conversation.conversation_stats
        return round(float(stats.get_combined_metrics().accumulated_cost), 4)
    except Exception:
        return None


def format_result(profile: ModelProfile, r: ProbeResult) -> str:
    lines = [
        f"model     : {profile.model}" + (f" @ {profile.base_url}" if profile.base_url else ""),
        f"verdict   : {r.verdict.upper()}",
        f"tool calls: {'yes' if r.tool_calls else 'no'} ({r.actions} actions)",
        f"risk label: {r.risk_labeled:.0%} of actions",
        f"confidence: {r.confidence:.0%} of actions",
        f"result    : {'verified pass' if r.verified else ('finished, not verified' if r.finished else 'did not finish')}",
        f"time      : {r.seconds}s" + (f", cost ${r.cost}" if r.cost else ""),
    ]
    for note in r.explain():
        lines.append(f"  - {note}")
    return "\n".join(lines)
