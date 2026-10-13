"""End-to-end: the real SDK loop + Grid's session, driven by the SDK's scripted
TestLLM. No model, no API key - but every layer runs for real: tool execution
in a terminal, file edits, the risk analyzer and confirmation policy, approvals,
checkpoints, regression revert, plan mode, step budget and verify-before-done."""

from __future__ import annotations

import json
import os
import sys

import pytest

pytest.importorskip("openhands.sdk.testing")

from openhands.sdk.llm import Message, MessageToolCall, TextContent  # noqa: E402
from openhands.sdk.testing import TestLLM  # noqa: E402

from grid.config import GridConfig  # noqa: E402
from grid.session import UI, GridSession, Outcome  # noqa: E402

PYTEST = f"{sys.executable} -m pytest -q -p no:cacheprovider"


class Script:
    """Builds scripted assistant turns."""

    def __init__(self):
        self.n = 0

    def call(self, name, args, *, risk="LOW", confidence=0.9):
        self.n += 1
        if name not in ("finish", "think") and risk is not None:
            args = {**args, "security_risk": risk}
        return Message(
            role="assistant",
            content=[TextContent(text=f"Next step.\nCONFIDENCE: {confidence}")],
            tool_calls=[MessageToolCall(id=f"call_{self.n}", name=name,
                                        arguments=json.dumps(args), origin="completion")],
        )

    def sh(self, command, **kw):
        return self.call("terminal", {"command": command}, **kw)

    def edit(self, path, old, new, **kw):
        return self.call("file_editor", {"command": "str_replace", "path": str(path),
                                         "old_str": old, "new_str": new}, **kw)

    def view(self, path, **kw):
        return self.call("file_editor", {"command": "view", "path": str(path)}, **kw)

    def finish(self, message="Done."):
        return self.call("finish", {"message": message})


class ScriptedUI(UI):
    def __init__(self, answers=(), interactive=True):
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.lines: list[str] = []
        super().__init__(say=self.lines.append, ask=self._ask, interactive=interactive)

    def _ask(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else ""

    @property
    def text(self):
        return "\n".join(self.lines)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gridhome"))
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"
    )
    (ws / "test_calc.py").write_text(
        "from calc import add, mul\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n"
    )
    return ws


def make_session(ws, messages, ui, verify_command=PYTEST, **cfg):
    # These scripts end at "finish"; the review round has its own tests (test_review.py).
    cfg.setdefault("self_review", False)
    config = GridConfig(condense_context=False, load_user_skills=False,
                        verify_command=verify_command, **cfg)
    return GridSession(str(ws), config, ui, llm=TestLLM.from_messages(messages),
                       persist=False, visualizer=None)


def test_happy_path_is_verified_and_checkpointed(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [
        s.sh(PYTEST),
        s.edit(project / "calc.py", "a - b", "a + b"),
        s.sh(PYTEST),
        s.finish("Fixed add."),
    ], ui)
    report = sess.submit("make the failing test pass")
    assert report.outcome is Outcome.VERIFIED
    assert "return a + b" in (project / "calc.py").read_text()
    assert any("calc.py" in c for c in report.changed)
    # the detector saw both real test runs from the terminal
    assert [(r.passed, r.failed) for r in sess.detector.history][:2] == [(1, 1), (2, 0)]
    assert len(sess.checkpoints.list()) >= 2


def test_red_action_is_asked_and_rejection_reaches_agent(project):
    (project / "build").mkdir()
    (project / "build" / "keep.txt").write_text("x")
    s = Script()
    ui = ScriptedUI(answers=["n"])
    # the model labels a recursive delete LOW; Grid's rules must still make it RED
    sess = make_session(project, [s.sh("rm -rf build", risk="LOW"), s.finish("ok")], ui)
    report = sess.submit("clean up")
    assert ui.prompts, "RED action ran without asking"
    assert "[RED]" in ui.text and "recursive delete" in ui.text
    assert "[a]lways" not in ui.prompts[0]  # can't blanket-approve RED
    assert (project / "build" / "keep.txt").exists()
    assert report.outcome is Outcome.DONE


def test_headless_rejects_red_without_prompting(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [s.sh("git push --force origin main", risk="LOW"), s.finish("ok")], ui)
    report = sess.submit("ship it")
    assert not ui.prompts
    assert "running unattended" in json.dumps([str(e) for e in sess.conversation.state.events])
    assert report.outcome is Outcome.DONE


def test_low_confidence_green_action_asks_first(project):
    s = Script()
    ui = ScriptedUI(answers=["y"])
    sess = make_session(project, [
        s.edit(project / "calc.py", "a - b", "a + b", confidence=0.2),
        s.finish("guessed"),
    ], ui)
    report = sess.submit("fix add")
    assert ui.prompts and "low confidence" in ui.text
    assert report.outcome is Outcome.VERIFIED


def test_regression_is_reverted_and_agent_told(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [
        s.sh(PYTEST),                                          # baseline 1/2
        s.edit(project / "calc.py", "a * b", "a ** b"),        # breaks mul
        s.sh(PYTEST),                                          # 0/2 -> regression -> revert
        s.edit(project / "calc.py", "a - b", "a + b"),         # the right fix
        s.sh(PYTEST),
        s.finish("Fixed."),
    ], ui)
    report = sess.submit("fix add")
    src = (project / "calc.py").read_text()
    assert "a * b" in src and "a ** b" not in src, "regressed change was not reverted"
    assert "[grid][undo] restored checkpoint" in ui.text
    assert report.outcome is Outcome.VERIFIED
    events = json.dumps([str(e) for e in sess.conversation.state.events])
    assert "detected a regression" in events
    assert any(e.kind == "regression" for e in sess.memory.all())


def test_done_is_not_accepted_until_verify_passes(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [
        s.edit(project / "calc.py", "def mul", "# touched\ndef mul"),  # unrelated change
        s.finish("All done!"),                                         # premature
        s.edit(project / "calc.py", "a - b", "a + b"),
        s.finish("Now really done."),
    ], ui)
    report = sess.submit("fix add")
    assert "[grid][verify] FAIL" in ui.text and "[grid][verify] PASS" in ui.text
    events = json.dumps([str(e) for e in sess.conversation.state.events])
    assert "before accepting" in events
    assert report.outcome is Outcome.VERIFIED


def test_unverified_after_max_attempts(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [
        s.edit(project / "calc.py", "def mul", "# touched\ndef mul"),
        s.finish("done"), s.finish("done"), s.finish("done"),
    ], ui, max_verify_attempts=2)
    report = sess.submit("fix add")
    assert report.outcome is Outcome.UNVERIFIED
    assert report.outcome.exit_code == 3


def test_plan_mode_blocks_writes_then_executes_after_approval(project):
    s = Script()
    ui = ScriptedUI(answers=["y"])
    sess = make_session(project, [
        s.view(project / "calc.py"),                               # read: allowed
        s.edit(project / "calc.py", "a - b", "a + b"),             # write: blocked in plan mode
        s.finish("OBJECTIVE: fix add\nSTEPS: 1. change - to +\nVERIFICATION: pytest"),
        s.edit(project / "calc.py", "a - b", "a + b"),             # executes after approval
        s.finish("Done."),
    ], ui)
    report = sess.submit("fix add", plan=True)
    assert "== PLAN ==" in ui.text and "OBJECTIVE: fix add" in ui.text
    assert any("Execute this plan" in p for p in ui.prompts)
    events = json.dumps([str(e) for e in sess.conversation.state.events])
    assert "Plan mode is read-only" in events
    assert report.outcome is Outcome.VERIFIED


def test_headless_plan_stops_at_plan(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [s.finish("OBJECTIVE: x")], ui)
    report = sess.submit("fix add", plan=True)
    assert report.outcome is Outcome.PLANNED
    assert "a - b" in (project / "calc.py").read_text()


def test_step_budget_checks_in(project):
    s = Script()
    ui = ScriptedUI(answers=["y", "y", "y"])
    sess = make_session(project, [
        s.sh("ls"), s.sh("pwd"), s.sh("ls -la"),   # distinct, so the stuck detector stays quiet
        s.finish("nothing to do"),
    ], ui, soft_step_budget=1)
    report = sess.submit("look around")
    assert sum("Continue?" in p for p in ui.prompts) >= 2
    assert report.outcome is Outcome.DONE


def test_headless_budget_pauses(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    cmds = ["ls", "pwd", "ls -la", "wc -l calc.py", "head -1 calc.py", "date"]
    sess = make_session(project, [s.sh(c) for c in cmds] + [s.finish("x")], ui,
                        soft_step_budget=1, headless_max_budgets=2)
    report = sess.submit("look around")
    assert report.outcome is Outcome.PAUSED


def test_undo_restores_previous_checkpoint(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [
        s.edit(project / "calc.py", "a - b", "a + b"), s.finish("ok"),
    ], ui)
    report = sess.submit("fix add")
    assert "a + b" in (project / "calc.py").read_text()
    msg = sess.undo(report.start_checkpoint.id)
    assert "restored checkpoint" in msg
    assert "a - b" in (project / "calc.py").read_text()


def test_session_persists_and_resumes(project):
    from grid.app import last_session_id

    s = Script()
    config = GridConfig(condense_context=False, load_user_skills=False, verify_command=PYTEST)
    first = GridSession(str(project), config, ScriptedUI(interactive=False),
                        llm=TestLLM.from_messages([s.sh("ls"), s.finish("looked")]), visualizer=None)
    first.submit("look around")
    sid = str(first.conversation.id)
    n_events = len(first.conversation.state.events)
    first.close()
    assert last_session_id(str(project)) == sid

    second = GridSession(str(project), config, ScriptedUI(interactive=False),
                         llm=TestLLM.from_messages([s.finish("still here")]), resume_id=sid,
                         visualizer=None)
    assert str(second.conversation.id) == sid
    assert len(second.conversation.state.events) >= n_events
    assert second.submit("anything else?").outcome is Outcome.DONE


def test_mcp_config_is_layered(project, tmp_path):

    from grid.app import load_mcp_config

    home = os.environ["GRID_HOME"]
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "mcp.json"), "w") as f:
        json.dump({"mcpServers": {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}}}, f)
    (project / ".grid").mkdir()
    (project / ".grid" / "mcp.json").write_text(json.dumps({"db": {"command": "db-mcp"}}))
    servers = load_mcp_config(str(project))
    assert set(servers) == {"fetch", "db"}


def test_cli_headless_end_to_end(project, monkeypatch):
    """`grid --headless "task"` through main(): real CLI, real session, scripted model."""
    from grid import app, cli

    s = Script()
    llm = TestLLM.from_messages([
        s.edit(project / "calc.py", "a - b", "a + b"),
        s.finish("fixed"),
    ])
    monkeypatch.setattr(app, "build_llm", lambda config: llm)
    monkeypatch.chdir(project)
    code = cli.main(["--headless", "--no-review", "--verify", PYTEST, "fix add"])
    assert code == 0
    assert "a + b" in (project / "calc.py").read_text()
    # and the checkpoint is there for `grid undo`
    assert cli.main(["undo", "0"]) == 0
    assert "a - b" in (project / "calc.py").read_text()


def test_cli_headless_unverified_exit_code(project, monkeypatch):
    from grid import app, cli

    s = Script()
    llm = TestLLM.from_messages([
        s.edit(project / "calc.py", "def mul", "# x\ndef mul"),
        s.finish("done"), s.finish("done"), s.finish("done"),
    ])
    monkeypatch.setattr(app, "build_llm", lambda config: llm)
    monkeypatch.chdir(project)
    assert cli.main(["--headless", "--no-review", "--verify", PYTEST, "fix add"]) == 3


# ---------------------------------------------------------------- autonomous mode

def test_autonomous_runs_yellow_without_asking_and_still_verifies(project):
    (project / "stale.txt").write_text("x")
    s = Script()
    ui = ScriptedUI()  # interactive terminal, but autonomous: must not prompt
    sess = make_session(project, [
        s.sh("rm stale.txt"),                                  # YELLOW
        s.edit(project / "calc.py", "a - b", "a + b", confidence=0.2),  # low confidence
        s.finish("done"),
    ], ui, autonomous=True)
    report = sess.submit("fix add and clean up")
    assert ui.prompts == []
    assert not (project / "stale.txt").exists()
    assert "AUTONOMOUS MODE" in ui.text and "[grid][verify] PASS" in ui.text
    assert report.outcome is Outcome.VERIFIED


def test_autonomous_refuses_red_that_was_not_preapproved(project):
    (project / "build").mkdir()
    (project / "build" / "x").write_text("x")
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [s.sh("rm -rf build"), s.finish("couldn't")], ui, autonomous=True)
    sess.submit("clean build")
    assert ui.prompts == []
    assert (project / "build" / "x").exists()
    assert "--allow delete" in ui.text
    events = json.dumps([str(e) for e in sess.conversation.state.events])
    assert "has not pre-approved" in events


def test_autonomous_runs_preapproved_red(project):
    (project / "build").mkdir()
    (project / "build" / "x").write_text("x")
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [s.sh("rm -rf build"), s.finish("cleaned")], ui,
                        autonomous=True, allow_red=frozenset({"delete"}))
    sess.submit("clean build")
    assert not (project / "build").exists()
    assert "pre-approved RED" in ui.text


def test_autonomous_never_runs_hard_blocked(project):
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [s.sh("sudo touch /etc/x"), s.finish("x")], ui,
                        autonomous=True, allow_red=frozenset({"delete", "push"}))
    sess.submit("do it")
    assert "never unattended" in ui.text


def test_three_refusals_end_with_needs_approval(project):
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [s.sh("git push"), s.sh("git push -f"), s.sh("git push origin HEAD")], ui,
                        autonomous=True)
    assert sess.submit("ship").outcome is Outcome.NEEDS_APPROVAL


@pytest.fixture
def untested(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gridhome"))
    ws = tmp_path / "untested"
    ws.mkdir()
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    return ws


def test_no_test_runner_agent_must_supply_a_real_check(untested):
    s = Script()
    ui = ScriptedUI()
    check = f"{sys.executable} check_add.py"
    sess = make_session(untested, [
        s.edit(untested / "calc.py", "a - b", "a + b"),
        s.finish("Fixed!"),                                 # no proof -> sent back
        s.finish("Fixed.\nVERIFY: true"),                   # fake proof -> refused
        s.call("file_editor", {"command": "create", "path": str(untested / "check_add.py"),
                               "file_text": "from calc import add\nassert add(2, 3) == 5\nprint('ok')\n"}),
        s.finish(f"Fixed, with a check.\nVERIFY: {check}"),
    ], ui, verify_command=None, autonomous=True, max_verify_attempts=3)
    report = sess.submit("fix add")
    assert "asking the agent to provide one" in ui.text
    assert "refused agent check `true`" in ui.text
    assert report.outcome is Outcome.VERIFIED
    assert report.verify is not None and report.verify.command == check


def test_agent_check_that_fails_is_not_accepted(untested):
    s = Script()
    ui = ScriptedUI(interactive=False)
    check = f"{sys.executable} check_add.py"
    sess = make_session(untested, [
        s.call("file_editor", {"command": "create", "path": str(untested / "check_add.py"),
                               "file_text": "from calc import add\nassert add(2, 3) == 5\n"}),
        s.finish(f"VERIFY: {check}"),                       # bug not fixed -> check fails
        s.edit(untested / "calc.py", "a - b", "a + b"),
        s.finish(f"VERIFY: {check}"),
    ], ui, verify_command=None, autonomous=True)
    report = sess.submit("fix add")
    assert "[grid][verify] FAIL" in ui.text
    assert report.outcome is Outcome.VERIFIED


def test_autonomous_plan_executes_without_asking(project):
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [
        s.finish("OBJECTIVE: fix add"),
        s.edit(project / "calc.py", "a - b", "a + b"),
        s.finish("Done."),
    ], ui, autonomous=True)
    report = sess.submit("fix add", plan=True)
    assert ui.prompts == []
    assert report.outcome is Outcome.VERIFIED


def test_autonomous_regression_reverts_without_asking(project):
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [
        s.sh(PYTEST),
        s.edit(project / "calc.py", "a * b", "a ** b"),
        s.sh(PYTEST),
        s.edit(project / "calc.py", "a - b", "a + b"),
        s.finish("Fixed."),
    ], ui, autonomous=True)
    report = sess.submit("fix add")
    assert ui.prompts == []
    assert "a ** b" not in (project / "calc.py").read_text()
    assert report.outcome is Outcome.VERIFIED


def test_autonomous_step_cap_pauses(project):
    s = Script()
    ui = ScriptedUI()
    cmds = ["ls", "pwd", "ls -la", "wc -l calc.py", "head -1 calc.py", "date"]
    sess = make_session(project, [s.sh(c) for c in cmds] + [s.finish("x")], ui,
                        autonomous=True, soft_step_budget=2, autonomous_max_steps=4)
    assert sess.submit("look").outcome is Outcome.PAUSED
    assert ui.prompts == []


def test_autonomous_keeps_going_past_each_check_in_and_still_verifies(project):
    # check-in every 2 steps; 5 steps of work then a fix: autonomous rolls through 3 check-ins
    # without asking, and "done" still has to pass the tests.
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [s.sh(c) for c in ["ls", "pwd", "wc -l calc.py", "head -1 calc.py"]]
                        + [s.edit(project / "calc.py", "a - b", "a + b"), s.finish("Fixed.")], ui,
                        autonomous=True, soft_step_budget=2, autonomous_max_steps=50)
    report = sess.submit("fix add")
    assert ui.prompts == []
    assert report.outcome is Outcome.VERIFIED
    assert ui.text.count("[grid][check-in]") == 2 and "4 steps so far" in ui.text


def test_autonomous_step_cap_is_exact(project):
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [s.sh(f"echo step {i}") for i in range(12)] + [s.finish("x")], ui,
                        autonomous=True, soft_step_budget=3, autonomous_max_steps=9)
    report = sess.submit("look")
    assert report.outcome is Outcome.PAUSED and report.message == "paused after 9 steps"
    assert "step cap (9) reached" in ui.text


def test_without_autonomous_grid_asks_at_each_check_in(project):
    s = Script()
    ui = ScriptedUI(answers=["n"])
    sess = make_session(project, [s.sh(f"echo step {i}") for i in range(5)] + [s.finish("x")], ui, soft_step_budget=2)
    report = sess.submit("look")
    assert report.outcome is Outcome.PAUSED and report.message == "paused after 2 steps"
    assert any("Continue?" in p for p in ui.prompts)


def test_turning_autonomous_off_restores_prompts(project):
    s = Script()
    ui = ScriptedUI(answers=["n"])
    sess = make_session(project, [s.sh("rm stale.txt"), s.finish("ok")], ui, autonomous=True)
    sess.set_autonomous(False)
    sess.submit("clean")
    assert ui.prompts  # YELLOW asks again


# ---------------------------------------------------------------- personality & lessons

def _suffix(sess):
    return sess.conversation.agent.agent_context.system_message_suffix


def test_default_voice_is_teacher(project):
    s = Script()
    sess = make_session(project, [s.finish("hi")], ScriptedUI(interactive=False))
    assert "YOUR VOICE: TEACHER" in _suffix(sess) and "YOUR VOICE: GRID" not in _suffix(sess)


def test_adult_gets_grid_voice_until_they_say_they_are_minor(project):
    from grid.persona import PersonaStore

    PersonaStore().answer_age("adult")
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [s.finish("sup"), s.finish("hello there")], ui)
    assert "YOUR VOICE: GRID" in _suffix(sess)
    sess.submit("hey, how's it going")
    sess.submit("I'm 15 years old, can you teach me python?")
    assert PersonaStore().load().minor_lock
    assert "Teacher mode is on" in ui.text
    sent = json.dumps([str(e) for e in sess.conversation.state.events])
    assert "[Grid mode: teacher]" in sent
    # a new chat starts in the teacher voice
    sess2 = make_session(project, [s.finish("hi")], ScriptedUI(interactive=False))
    assert "YOUR VOICE: TEACHER" in _suffix(sess2)


def test_cli_teacher_flag_always_wins(project):
    from grid.persona import PersonaStore

    PersonaStore().answer_age("adult")
    sess = make_session(project, [], ScriptedUI(interactive=False), persona="teacher")
    assert "YOUR VOICE: TEACHER" in _suffix(sess)
    # asking for grid without an adult answer doesn't unlock it
    PersonaStore().answer_age("minor")
    sess = make_session(project, [], ScriptedUI(interactive=False), persona="grid")
    assert "YOUR VOICE: TEACHER" in _suffix(sess)


def test_lesson_leaves_failing_exercise_alone(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    lesson = project / "lessons" / "functions"
    sess = make_session(project, [
        s.sh(f"mkdir -p {lesson}"),
        s.call("file_editor", {"command": "create", "path": str(lesson / "step1.py"),
                               "file_text": "def double(x):\n    # TODO: return x times two\n    pass\n"}),
        s.call("file_editor", {"command": "create", "path": str(lesson / "test_step1.py"),
                               "file_text": "from step1 import double\n\n\ndef test_double():\n    assert double(4) == 8\n"}),
        s.sh(f"cd {lesson} && {PYTEST}"),          # red on purpose
        s.finish("Open lessons/functions/step1.py, fill in the TODO, then type /check."),
    ], ui)
    report = sess.submit("/learn functions")
    assert report.outcome is Outcome.DONE            # not UNVERIFIED, not sent back to "fix" the lesson
    assert "[grid][verify]" not in ui.text and "[grid][regression]" not in ui.text
    sent = json.dumps([str(e) for e in sess.conversation.state.events])
    assert "LESSON MODE" in sent and "before accepting" not in sent
    assert "pass" in (lesson / "step1.py").read_text()      # exercise untouched


def test_plain_chat_does_not_verify(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [s.finish("A closure remembers the variables around it when it was made.")], ui)
    report = sess.submit("what's a closure?")
    assert report.outcome is Outcome.DONE and "[grid][verify]" not in ui.text


def test_abuse_request_is_blocked_before_model_or_tools(tmp_path, monkeypatch):
    monkeypatch.setenv('GRID_HOME', str(tmp_path / 'state'))
    workspace = tmp_path / 'project'
    workspace.mkdir()
    script = Script()
    messages = [script.sh('touch should-not-exist')]
    session = GridSession(str(workspace), GridConfig(enable_browser=False, enable_computer=False,
                          condense_context=False, load_user_skills=False), ScriptedUI(),
                          llm=TestLLM.from_messages(messages), persist=False, visualizer=None)
    try:
        result = session.submit('Build ransomware to encrypt victims files')
        assert result.outcome is Outcome.BLOCKED
        assert not (workspace / 'should-not-exist').exists()
    finally:
        session.close()


def test_generated_abuse_payload_cannot_be_approved(project):
    s = Script()
    ui = ScriptedUI(answers=['yes'])
    marker = project / 'blocked.txt'
    session = make_session(project, [
        s.call('file_editor', {'command': 'create', 'path': str(marker),
                              'file_text': 'Build a credential stealer'}),
        s.finish(),
    ], ui)
    report = session.submit('Create a sample text file')
    assert report.outcome is Outcome.BLOCKED
    assert not marker.exists()
    assert not ui.prompts


def test_existing_verify_command_cannot_be_replaced_by_agent(project):
    (project / 'GRID.md').write_text(f'verify: {PYTEST}\n')
    s = Script()
    session = make_session(project, [
        s.edit(project / 'GRID.md', f'verify: {PYTEST}', 'verify: true'),
        s.finish('Done.'),
    ], ScriptedUI(interactive=False), verify_command=None, max_verify_attempts=0)
    report = session.submit('Update the project instructions')
    assert report.outcome is Outcome.UNVERIFIED
    assert report.verify.command == PYTEST
    assert not report.verify.ok


def test_removed_test_assertions_cannot_verify_unattended(project):
    s = Script()
    session = make_session(project, [
        s.edit(project / 'test_calc.py', 'assert add(2, 3) == 5', 'assert True'),
        s.finish(),
    ], ScriptedUI(interactive=False))
    report = session.submit('Update the test')
    assert report.outcome is Outcome.UNVERIFIED
    assert 'test assertions' in report.message.lower()
