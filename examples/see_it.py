"""See Grid AI's brain make decisions — no model, no Docker, no API key.

This exercises the REAL Grid AI modules (the same code the live agent uses),
just without the LLM loop. Run it with:

    PYTHONPATH=src python examples/see_it.py
"""

from grid.confidence_emit import parse_confidence
from grid.enforcement import effective_risk_value
from grid.memory import Episode, MemoryStore
from grid.regression import RegressionDetector, parse_pytest_summary
from grid.teaching import DepthLevel, teaching_prompt
from grid.tiers import should_confirm_for_risk_value

BAR = "─" * 66


def section(title):
    print(f"\n{BAR}\n  {title}\n{BAR}")


# 1) THE RISK GATE ------------------------------------------------------------
section("1. The risk gate — what runs freely vs. what stops and asks")
actions = [
    ("read a file", "LOW"),
    ("edit a source file", "LOW"),
    ("run the tests", "LOW"),
    ("pip install a new dependency", "MEDIUM"),
    ("git push to main", "HIGH"),
    ("rm -rf the project folder", "HIGH"),
]
for label, risk in actions:
    confirm = should_confirm_for_risk_value(risk, confirm_yellow=True, confirm_unknown=True)
    verdict = "⛔ STOP & ASK" if confirm else "✅ run freely"
    print(f"  {verdict:<14} {label}  (risk={risk})")

# 2) CONFIDENCE ENFORCEMENT ---------------------------------------------------
section("2. Confidence enforcement — being unsure makes it more cautious")
print("  The model self-rates each action. Low confidence escalates the risk,")
print("  so a 'guess' on a normally-free action becomes ask-first.\n")
for label, thought in [
    ("edit file, sure",     "This is clearly the fix.\nCONFIDENCE: 0.95"),
    ("edit file, guessing", "Not sure this is right, trying it.\nCONFIDENCE: 0.3"),
    ("delete files, sure",  "I'll remove these.\nCONFIDENCE: 0.99"),
]:
    conf = parse_confidence(thought)
    base = "LOW" if "edit" in label else "HIGH"
    eff = effective_risk_value(base, conf)
    confirm = should_confirm_for_risk_value(eff)
    change = f"{base} → {eff}" if eff != base else f"{base} (unchanged)"
    verdict = "⛔ STOP & ASK" if confirm else "✅ run freely"
    print(f"  {label:<20} conf={conf:<4} risk {change:<18} {verdict}")
print("\n  Note: HIGH stays HIGH even at 0.99 confidence — risk always beats confidence.")

# 3) REGRESSION DETECTOR ------------------------------------------------------
section("3. Regression detector — it notices when a 'fix' makes things worse")
detector = RegressionDetector()
runs = [
    "collected 5 items\n\n======================== 4 passed, 1 failed in 0.3s ========================",
    "collected 5 items\n\n======================== 2 passed, 3 failed in 0.3s ========================",
]
for out in runs:
    r = parse_pytest_summary(out)
    assert r is not None and r.pass_ratio is not None
    detector.record(r)
    print(f"  test run → {r.passed} passed / {r.failed} failed  (pass rate {r.pass_ratio:.0%})")
if detector.is_regression():
    print(f"\n  ⚠️  {detector.reason()}")

# 4) CROSS-SESSION MEMORY -----------------------------------------------------
section("4. Cross-session memory — it remembers this project's past mistakes")
import tempfile, pathlib
store = MemoryStore(project="demo", root=pathlib.Path(tempfile.mkdtemp()))
store.add(Episode(
    error_signature="forgot to await async fetch()",
    lesson="fetch() returns a coroutine; await it or you get a coroutine object.",
    kind="failure",
))
print("  [last session] recorded a lesson: forgot to await async fetch()\n")
print("  [this session] user asks: 'my fetch call returns a weird object'")
recall = store.recall_prompt("my async fetch call returns a weird object")
print("  → Grid injects this into the agent's context:\n")
for line in recall.splitlines():
    print(f"      {line}")

# 5) TEACHING LAYER -----------------------------------------------------------
section("5. Teaching layer — the depth dial changes how much it explains")
for level in (DepthLevel.BEGINNER, DepthLevel.PRO):
    print(f"\n  --- depth = {level.value} ---")
    print("  " + teaching_prompt(level).replace("\n", "\n  "))

print(f"\n{BAR}\n  That's the decision engine. The live agent adds the LLM + its own")
print(f"  terminal on top (see RUNBOOK.md when you're ready to run it for real).\n{BAR}")
