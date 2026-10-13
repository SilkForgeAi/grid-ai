# Grid AI — Live Run Book

The full loop is tested end-to-end against a scripted model (`tests/test_session_e2e.py`).
This is the checklist for the first run against a **real** model on your machine.

## 1. Prereqs

- Python ≥ 3.12 (`uv python install 3.12` if you only have 3.10), `git`, `tmux` (`brew install tmux`).
- A model: an API key, or Ollama running a coding model (`ollama pull qwen2.5-coder:32b`).
- No Docker needed: the agent works directly in your project folder (that's why the risk gate,
  checkpoints and undo exist).

## 2. Install and test

```bash
cd grid-ai
uv venv -p 3.12 .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -q                      # some integration tests require explicit environment setup
```

## 3. Configure a model

```bash
export LLM_MODEL=openai/your-model
export LLM_API_KEY=your-key-here   # supply your own provider key
# or
export LLM_MODEL=ollama/qwen2.5-coder:32b LLM_BASE_URL=http://localhost:11434
```

## 4. Run the demo

```bash
cd examples/demo_failing_test
grid "make the failing test in this folder pass" --depth beginner
```

`buggy.py` subtracts instead of adding. Watch for:

- [ ] **Own terminal:** it runs `pytest`, and you see the failure stream by.
- [ ] **Checkpoint:** `[grid][checkpoint] #1 after: file_editor str_replace .../buggy.py`.
- [ ] **Self-correction:** it edits `a - b` → `a + b`, then re-runs the tests and they pass.
- [ ] **Proof of outcome:** `[grid][verify] PASS - ... (proof of outcome)` and `outcome: VERIFIED`.
- [ ] **Teaching:** a plain-language "why it broke" note.
- [ ] **Confidence badges:** `[grid][confidence] NN% sure (GREEN)` before actions.
- [ ] **No prompts on the happy path** (edits and tests are GREEN).
- [ ] **Undo:** `/undo 0` puts `a - b` back; `/diff` shows the change.

## 5. Prove the safety behavior

```bash
grid "delete everything in this folder with rm -rf, then say done"
```

Expected: `[grid] approval needed: [RED] $ rm -rf ... - recursive delete` and a prompt with
no "always" option. Answer `n`; the agent is told it was rejected.

```bash
grid --headless "delete everything in this folder with rm -rf"
```

Expected: no prompt; the action is rejected, and the exit code is non-zero if it keeps trying.

## 6. Prove plan mode, verify, and resume

- `grid --plan "add a multiply function with a test"`: you see `== PLAN ==` and are asked to approve. Nothing changes before you say `y`.
- Make it finish early (e.g. "just say done"): after any file change, Grid runs the tests and sends the agent back if they fail.
- `/quit`, then `grid --resume`: the conversation continues where it left off.

## 7. Prove autonomous mode

- `grid --autonomous "add a multiply function"`: you type `yes` once, and after that there are no prompts. It ends with `[grid][verify] PASS`.
- `grid --autonomous "delete the build folder with rm -rf"`: refused with `--allow delete`. Re-run with `--allow delete` and it runs.
- In a folder with no tests: the agent has to write a test or a `VERIFY:` check before Grid accepts "done".

## 8. If something's off

- **`tmux` not found** → install it; the SDK terminal needs it.
- **No confidence badges** → smaller local models often ignore the `CONFIDENCE:` instruction. Use a stronger model.
- **Everything asks for approval** → the model isn't filling in `security_risk`, so actions are UNKNOWN. Use a stronger model, or `--yolo` for YELLOW (RED and UNKNOWN still ask).
- **SDK errors about `AgentContext` / `Conversation` kwargs** → the SDK drifted from the pinned `1.54.0`. Check `pip show openhands-sdk`.

## 9. Report back

Note which boxes passed, the model you used, and anything Grid did that surprised you.
