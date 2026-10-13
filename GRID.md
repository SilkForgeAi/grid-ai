# Instructions for agents working on Grid AI itself

- Python >= 3.12. Source in `src/grid`, tests in `tests`.
- Keep the pure modules (`tiers`, `rules`, `confidence*`, `enforcement`, `regression`,
  `memory`, `checkpoints`, `project`, `events`, `verify`, `teaching`) free of SDK imports.
  SDK imports belong in `app.py`, `policy.py`, `analyzer.py`, `session.py` (deferred where possible).
- Invariant: a RED action never runs without a human's approval (at the prompt, or pre-approved by
  category in autonomous mode). Hard-blocked categories are never pre-approvable. Keep it that way.
- Every bug fix gets a test that fails without the fix.

verify: python -m pytest -q
