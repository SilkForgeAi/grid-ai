# Grid

**Learn to code. Have fun building. Free and open source under MIT.**

Build a small game, ask for a hint, or explore how an agent works. Fork Grid,
read the code, and make it your own. Start with the [beginner guide](#personality-and-lessons)
or the [desktop app instructions](desktop/README.md).

**Source preview:** macOS development is supported; Windows installers are not yet
available. There are no supported public app downloads yet. Each user brings their
own model and credentials. No publisher API keys, saved profiles, or model weights
are included.

A self-correcting, teaching-first coding agent, built **on**
[`openhands-sdk`](https://github.com/OpenHands/software-agent-sdk) rather than
forked from it. The SDK provides the agent loop, the terminal, file editing, the
event stream, persistence, context condensation, skills and MCP. Grid adds the
review, teaching and execution controls described below. This is a prerelease;
read [the safety boundaries](SAFETY.md) before running untrusted code.

- **Risk-tiered autonomy.** GREEN runs freely, YELLOW asks, RED always asks. The tier is the
  worst of the model's own label, a confidence escalation, and Grid's deterministic rules
  (`rm -rf`, `git push`, publishing, deploys, secrets, writes outside the project are RED
  whatever the model says).
- **Checkpoints and undo.** Every change is a checkpoint in a private shadow git repo.
  Your own repo, index and history are never touched, and it works in non-git folders too.
- **Regression revert.** If a change lowers the test pass rate, Grid restores the last good
  checkpoint and tells the agent to try something else.
- **Independent checks.** Changed code is accepted as verified after Grid runs the project's check itself
  and it passes. Passing a check is evidence within its coverage. If it fails, the agent is sent back to fix it.
- **Plan mode.** Read-only investigation, then a plan you approve, then execution.
- **Autonomous mode.** Approve once up front and Grid stops asking. It still refuses RED actions
  you didn't pre-approve, and a task still only counts as done when a real check passes.
- **Memory.** Lessons from regressions and failed verifications are recalled into later tasks
  in the same project.
- **Teaching.** A depth dial (beginner / intermediate / pro / off) and "why did this break" notes.

## Install

```bash
git clone https://github.com/SilkForgeAi/grid-ai.git
cd grid-ai
uv venv -p 3.12 .venv && source .venv/bin/activate     # or python3.12 -m venv .venv
uv pip install -e ".[dev]"                              # or pip install -e ".[dev]"
```

You need Python ≥ 3.12, `git` and `tmux` (the SDK's terminal uses it: `brew install tmux`).

## Personality and lessons

Grid is for teaching adults to code: step by step, in conversation. You can also just talk to it.
It has two voices:

- **Grid (18+):** the senior engineer who got tired of babysitting juniors but still cares enough to
  roast you into competence. Dry, funny, swears when it lands. It roasts the code, never the person.
  It drops the jokes completely when you're genuinely lost.
- **Teacher:** the same skills and lessons, with clean language and extra patience.

The age line:

- The Grid voice unlocks only after you answer "18 or older". That happens on first launch, in
  Settings → Personality, or with `grid persona adult`. Until then, and by default, Grid is the
  teacher.
- Answering "under 18", or saying so in chat ("I'm 15", "I'm in 8th grade"), switches to teacher
  mode immediately and locks it. Only re-confirming 18+ in Settings undoes that.
- Age is self-declared. Grid only stores the answer, never your age, and it errs toward the teacher.
- Code, comments and files Grid writes stay professional in both voices.

Lessons have you write the code. Grid sets up the exercise and checks your work:

| Command | What it does |
|---|---|
| `/learn <topic>` | Builds a lesson plan, a starter file with TODOs, and a test for step 1 |
| `/hint` | Gives a nudge for the current step, not the answer |
| `/check` | Runs your work against the step's test and explains the result |
| `/next` | Moves on to the next step |
| `/solution` | Shows and explains a solution for the current step |
| `/quiz [topic]` | Asks three quick questions to check the idea stuck |

Lesson tasks skip verify-before-done and regression revert, because a lesson's test is supposed to
fail until you solve it.

## Bring your own model

Grid works with any model [LiteLLM](https://docs.litellm.ai/docs/providers) supports: Anthropic,
OpenAI, Gemini, DeepSeek, OpenRouter, Bedrock, Ollama, LM Studio, vLLM, or any OpenAI-compatible
server. With nothing configured, it uses `anthropic/claude-opus-5-5` and your `ANTHROPIC_API_KEY`.

```bash
# save profiles once
grid models add work  --model anthropic/claude-opus-5-5 --key-env ANTHROPIC_API_KEY --default
grid models add cheap --model anthropic/claude-sonnet-5-5
grid models add local --model ollama/qwen3.6:27b --base-url http://localhost:11434
grid models add box   --model openai/my-model --base-url http://192.168.1.20:8000/v1 --prompted-tools

grid models test local          # run a small real task: does this model work with Grid?
grid models                     # list profiles, the default (*), and each one's test verdict
grid models use cheap           # change the default

grid --profile local "task"     # pick a profile for one run
grid --model openai/gpt-5.5 "task"   # or any model id, ad hoc
grid --local-only "task"        # refuse any model or MCP server that leaves this machine
```

In a session, `/model` shows the current model and `/model NAME` switches profiles. The
conversation history is kept when you switch.

- **Profiles never contain API keys.** A profile stores the *name* of the env var that holds its key
  (`--key-env`). Without one, Grid uses `LLM_API_KEY`, then the provider's own variable.
  Session files store keys masked.
- **`grid models test`** checks what Grid's safety layer depends on: does the model call tools,
  label each action's risk, report confidence, and get a small bug to a verified pass? It
  reports one of three verdicts:
  - **READY**: works fully with Grid.
  - **USABLE**: works, but expect more approval prompts.
  - **NOT-READY**: it explains why, for example suggesting `--prompted-tools` for models without
    tool calling.
- **`--prompted-tools`** describes tools in the prompt for models without native tool calling.
- **Precedence:** `--model`, then `--profile`, then `$GRID_PROFILE`, then `$LLM_MODEL`, then the
  default profile, then the built-in default.

Choose a model that supports tool calls and test its behavior with `grid models test`.
Check your provider’s current availability and pricing before using a cloud model.

Small local models tend to skip the confidence line and the risk label. Grid then treats their
actions as UNKNOWN, which means more prompts (or refusals in headless/autonomous mode).

## The Grid app

**Grid is a native desktop learning workshop.** Its geometric G mark, warm canvas,
and three focused modes give your project, code, and guide room to breathe.
The current Mac build is a local prerelease; public signed Mac and Windows downloads
are not ready. Build instructions are in [desktop/README.md](desktop/README.md).

- **Play:** run your project in the terminal and see what happens.
- **Code:** open Files and edit with Monaco. Save with ⌘S (Ctrl+S on Windows/Linux).
- **Understand:** focus the conversation, ask for a hint, and review approval requests.
  Switching these modes preserves your draft, open files, and terminal session.
- **Particle Lab:** a live GPU particle sculpture inspired by a swirling ash-and-ember
  reference, with 600,000 particles in the Lab and 260,000 on Home. The default
  motion is seven times faster than the first version, with Flow adjustable up to 1,000%.
  Drag or use arrow keys to turn it; adjust Flow, Shape, and Ember light;
  try three palettes. Pause and Reset are always within reach. This is a procedural
  recreation, not an embedded video or an exact fluid simulation.
- **Workspace backboard:** an ambient particle scene replaces the oversized logo.
  It stays visible while you chat and receive replies, and fades away when you open a file or use the terminal.
  **Particles ↗** brings it back fullscreen; Escape or **Back to workspace** returns
  you to work. Visible particles give a small, capped glow and motion pulse as
  Grid streams new reply text, settling naturally between chunks. Pause and Reduce
  Motion suppress the reaction. The hidden scene releases its graphics resources.
- **Start here:** an in-app beginner guide covering projects, models, commands,
  changes, checkpoints, approvals, and common questions.
- **Comfortable motion:** native trackpad/wheel scrolling, batched chat updates,
  and a Latest messages button when you read earlier output. Particles pause offscreen
  and when the app is hidden. Reduce Motion starts the effect paused; unavailable
  graphics fall back to a still treatment. The Lab needs no model or account.

### Your first small win

1. Open **Start here**, then **Start Tiny Arcade**. Choose a new project folder.
2. Read the project guide in **Play**. Run `python3 main.py` in its terminal.
3. Choose **Code → Files → main.py**, change the secret number, save, and run again.
4. Set up a model in **Models** to ask Grid questions. Cloud providers may charge;
   local models need a compatible local runtime.
5. Use **Give me a hint** to draft a question. Read it, then send it when ready.
6. Run `python3 -m unittest discover -v`, inspect **Changes**, and use **Checkpoints**
   to recover earlier work. Tests only establish what they actually check.

Read each approval request. Keep Autonomous off while learning. **Trusted host**
commands use your account’s permissions; **Container + policy review** requires
restricted-mode configuration. No system can guarantee that every harmful request
or program will be caught. See [SAFETY.md](SAFETY.md).

The desktop app starts its local engine and provides native menus, a folder picker,
and encrypted Keychain storage for API keys. `grid app` also exposes the same local
interface in a browser for development.

- **Projects:** create a project (empty or Python template, optional `git init`), or open any folder.
- **Files:** a file tree with new file, new folder, rename and delete. Deleting moves the file to
  `~/.grid/trash` and takes a checkpoint first. There's also a built-in editor, and saving takes a
  checkpoint too.
- **Agent workspace:**
  - Streaming chat with every action Grid takes, its risk level, the model's confidence, and the
    command output.
  - Approval cards inline with Yes, No, or a typed reason. For RED actions the focus starts on No.
  - Plan-first mode, autonomous mode (you confirm it by typing `yes`), choosing the model per
    project, and the teaching depth.
  - Side panel tabs:
    - **Changes:** a diff of everything since the task started.
    - **Checkpoints:** restore any point.
    - **Terminal:** every command the agent ran.
    - **File:** the editor.
  - "Undo this task" on every result card.
- **Plugins:** a catalog (starter plugins: `python-quality`, `git-workflow`, `docs-writer`, `teach`,
  `web-fetch`), installing from a folder or git, on/off switches, and per-project scope. Plugins use
  the **Claude Code plugin format** (`.claude-plugin/plugin.json`, `skills/`, `commands/`,
  `.mcp.json`), so those plugins work as-is. You see everything a plugin adds before installing it.
  Commands show up as `/plugin:command` in the composer.
- **Models:** saved model profiles, the default model, and a one-click compatibility test.
- **Schedules:** recurring tasks with cron or presets, either unattended or autonomous with
  pre-approved categories, plus run history and logs.
- **Memory:** see and delete the lessons Grid saved per project.
- **Settings:** defaults for new chats, and the theme (system, light or dark).

Security: the app listens on 127.0.0.1 only and checks the Host header. You sign in with a random
link printed at startup, which sets an HttpOnly, SameSite=Strict cookie. Every change also needs a
custom header, websockets check the Origin, and a strict CSP is set.

The CLI equivalents: `grid plugins ...`, `grid schedule ...`, `grid models ...`. A browser smoke test
lives in `scripts/ui_smoke.py`.

## Use

```bash
grid "make the failing test pass"          # run a task, then stay for follow-ups
grid                                       # interactive session
grid --plan "add a --version flag"         # plan -> approve -> execute
grid --headless "fix the lint errors"      # unattended (CI / scheduled): never prompts
grid --autonomous "build the CSV export"   # approve once, then no prompts (see below)
grid --autonomous --allow push "..."       # ...and it may also git push
grid --resume                              # continue the last session in this folder
grid checkpoints | grid undo [N] | grid diff [N] | grid sessions
```

Inside a session: `/plan <task>`, `/auto [on|off] [--allow a,b]`, `/undo [N]`, `/diff [N]`,
`/checkpoints`, `/verify`, `/depth <level>`, `/yolo`, `/help`, `/quit`.

## Autonomous mode

`grid --autonomous` (or `/auto` in a session) shows what it will and won't do. It switches on
only after you type `yes`; `--yes` skips that prompt for scripts.

- **Runs without asking:** GREEN and YELLOW actions. UNKNOWN actions stop for human review.
- **RED actions:** refused, and the agent is told why, unless you pre-approved the category with
  `--allow`: `delete`, `git-history`, `push`, `publish`, `deploy`, `network-exec`, `permissions`,
  `model-flagged`.
- **Never unattended, even with --allow:** root/sudo, disk writes, credentials and secrets, writes
  outside the project, system services, `.git` internals. A human can still approve these one at
  a time in a normal session.
- **Always on:** checkpoints, automatic revert on regressions, a step cap (300 per task), and
  **mandatory verification.** "Done" counts only after Grid runs a check itself and it passes.
  If the project has no test runner, the agent must write a test, or name a check with a
  `VERIFY: <command>` line. Grid rejects no-op checks (`true`, `echo`, `|| true`, ...) and RED
  commands. After three refused actions in a row, the task stops with exit code 4.

Useful flags: `--depth beginner|intermediate|pro|off`, `--verify "<cmd>"`, `--no-verify`,
`--step-budget N` (check in every N steps), `--yolo` (don't ask for YELLOW; RED still asks),
`--confidence-threshold`, `--strict-confidence`, `--browser`, `--sub-agents` (off by default
because they multiply token cost).

Exit codes: `0` verified/done · `1` error · `2` usage · `3` unverified · `4` needed approval
(headless) · `5` stuck · `6` paused.

## Project instructions

Grid reads, in order (later wins): `~/.grid/GRID.md`, `GRID.md` at the git root, then `GRID.md`
in the working folder. It also picks up `AGENTS.md`, `CLAUDE.md`, `.cursorrules` and
`.agents/skills/` through the SDK, so repos set up for other agents work unchanged.

A `verify:` line sets the check Grid runs before accepting changed code as verified:

```markdown
verify: python -m pytest -q
```

Without one, Grid detects `npm test`, `cargo test`, `go test ./...` or pytest.

MCP servers: `~/.grid/mcp.json` and `<project>/.grid/mcp.json`
(`{"mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}}}`).
MCP tools are YELLOW by default.

State lives in `~/.grid/` (override with `GRID_HOME`): `memory/`, `checkpoints/`, `sessions/`,
all keyed by the project's absolute path.

## Design invariant

**A RED action never runs without a human's approval.** That approval is given either at the
prompt, or up front for a named category with `--autonomous --allow`. No confidence score, `--yolo`
or "always allow" can bypass it. Hard-blocked categories can only be approved at the prompt.

## Layout

| Module | Role | SDK? |
|---|---|---|
| `session.py` | Drives the loop: approvals, checkpoints, regression revert, plan mode, budget, verify | yes |
| `app.py` | Builds LLM, tools, agent context, conversation | yes (deferred) |
| `analyzer.py` / `policy.py` | Risk analyzer (model ∨ confidence ∨ rules) and the GREEN/YELLOW/RED gate | yes |
| `rules.py` | Deterministic RED/YELLOW rules and RED categories; read-only detection for plan mode | no |
| `autonomy.py` | Autonomous-mode policy: pre-approved vs hard-blocked RED categories | no |
| `models.py` / `probe.py` | Model profiles, key handling, local-only checks; the `grid models test` probe | only to build an LLM |
| `checkpoints.py` | Shadow-git checkpoints, restore, diff | no |
| `verify.py` / `project.py` | Verify command runner; project key, GRID.md, verify detection | no |
| `regression.py` | Test-regression detector (skip/scope/collection-error aware) | no |
| `memory.py` | Per-project episodic memory | no |
| `confidence*.py`, `enforcement.py`, `tiers.py`, `teaching.py`, `events.py`, `config.py` | Supporting pure logic | no |
| `cli.py` | CLI, REPL, subcommands | no (until a task runs) |
| `server/` | The app: API + websocket (`api.py`), session bridge (`runtime.py`), projects and safe file ops, static UI | yes |
| `plugins.py` / `plugins_builtin/` | Plugin install/enable/remove (Claude Code format), slash-command expansion, starter catalog | yes (loader) |
| `schedules.py` / `settings.py` | Cron schedules + runner; app defaults | no |

## Test

```bash
pytest -q        # 305 tests: unit tests plus scripted end-to-end runs through the real SDK loop
ruff check src tests
```

The end-to-end tests (`tests/test_session_e2e.py`) use the SDK's `TestLLM`, so the whole loop
runs for real with no model or API key: terminal commands, file edits, approvals, checkpoints,
regression revert, plan mode, autonomous mode, the step budget, verify-before-done, resume, and the CLI.

## Status

Grid is a source preview with an Electron desktop workshop, scripted agent tests,
and a local particle lab. Start with [desktop/README.md](desktop/README.md) to run
the native app. Windows native support, consumer installers, and distribution
review remain unfinished; see [release status](docs/release/RELEASE.md).

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. Copyright (c) 2026 Aaron Dennis (SilkForge AI). You may use, learn from, modify,
and redistribute Grid under [LICENSE](LICENSE).
Third-party components keep their own licenses - see `THIRD_PARTY_NOTICES.md`.


### Safety and release readiness

Grid adds a shared abuse policy to agent and quick replies, checks explicit harmful intent before tasks and tool approvals, and blocks unknown actions in unattended mode. These checks reduce risk; they do not guarantee that generated code is harmless. See [SAFETY.md](SAFETY.md) for limits and the remaining release requirements.

Editor saves carry a file version to detect stale writes. Chat tasks, schedules, editor writes and manual verification share a project lock. Stop and timeouts terminate verification process groups. Checks with zero passing tests or reported failures cannot receive a verified result. Existing check commands are frozen before an agent task; removal or skipping of test evidence requires human review.


Desktop distribution, restricted execution, policy-service setup, dependency
license findings and notarization procedures are tracked in
[docs/release/RELEASE.md](docs/release/RELEASE.md). The restricted mode is opt-in;
the installed trusted-host workflow must not be represented as fully sandboxed.
