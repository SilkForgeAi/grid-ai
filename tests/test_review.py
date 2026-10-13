"""Consistency before "done": Grid's own quick checks on changed files, and one review round
where the agent re-reads its changes. Scripted model, real session, real tests."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("openhands.sdk.testing")
from test_session_e2e import Script, ScriptedUI, make_session  # noqa: E402

from grid.consistency import changed_paths, review_request, static_problems  # noqa: E402
from grid.session import Outcome  # noqa: E402


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gridhome"))
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n")
    (ws / "test_calc.py").write_text(
        "from calc import add, mul\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n"
    )
    return ws


def _sent(sess) -> str:
    """Everything sent to the agent as user messages in this chat."""
    out = []
    for e in sess.conversation.state.events:
        if type(e).__name__ == "MessageEvent" and e.source == "user":
            out.append("".join(getattr(c, "text", "") for c in e.llm_message.content))
    return "\n".join(out)


# ---------------------------------------------------------------- Grid's own quick checks

def test_changed_paths_skips_deletions_and_vendor_folders():
    lines = ["M\tcalc.py", "D\told.py", "R100\tsrc/a.py\tsrc/b.py", "A\tweb/node_modules/x/index.js", "A\tnotes.md"]
    assert changed_paths(lines) == ["calc.py", "src/b.py", "notes.md"]


def test_static_problems_find_broken_files_only(tmp_path):
    (tmp_path / "ok.py").write_text("def f():\n    return 1\n")
    (tmp_path / "bad.py").write_text("def f(:\n    return 1\n")
    (tmp_path / "bad.json").write_text('{"a": 1,}')
    (tmp_path / "ok.json").write_text('{"a": 1}')
    (tmp_path / "bad.toml").write_text("name = \n")
    (tmp_path / "merge.txt").write_text("a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> branch\n")
    (tmp_path / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe")
    changed = [f"M\t{n}" for n in ("ok.py", "bad.py", "bad.json", "ok.json", "bad.toml", "merge.txt", "pic.png",
                                   "missing.py", "../outside.py")]
    found = static_problems(str(tmp_path), changed)
    assert len(found) == 4
    assert any(p.startswith("bad.py line 1: Python syntax error") for p in found)
    assert any(p.startswith("bad.json line 1: not valid JSON") for p in found)
    assert any(p.startswith("bad.toml: not valid TOML") for p in found)
    assert any(p.startswith("merge.txt line 2: merge-conflict markers") for p in found)


def test_review_request_lists_files_and_known_problems():
    text = review_request(["calc.py", "README.md"], ["calc.py line 3: Python syntax error (x)"])
    assert "- calc.py\n- README.md" in text and "fix them first" in text and "REVIEW:" in text
    many = review_request([f"f{i}.py" for i in range(30)])
    assert "...and 5 more" in many


# ---------------------------------------------------------------- the review round

def test_review_runs_once_before_done_and_tests_still_decide(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [
        s.edit(project / "calc.py", "a - b", "a + b"),
        s.finish("Fixed add."),
        # the review round: re-read the change, then finish again
        s.view(project / "calc.py"),
        s.finish("Fixed add.\nREVIEW: checked add() and its test; no issues found"),
    ], ui, self_review=True)
    report = sess.submit("fix add")
    assert report.outcome is Outcome.VERIFIED
    assert ui.text.count("[grid][review]") == 1 and "Re-reading 1 changed file" in ui.text
    sent = _sent(sess)
    assert "review your own changes for consistency" in sent and "- calc.py" in sent
    assert "REVIEW: checked add()" in report.message
    # the review came before the check: PASS is reported after the review line
    assert ui.text.index("[grid][review]") < ui.text.index("[grid][verify] PASS")


def test_review_fixes_what_grid_found_and_runs_in_autonomous_mode(project):
    s = Script()
    ui = ScriptedUI()
    sess = make_session(project, [
        s.edit(project / "calc.py", "return a - b", "return (a + b"),       # broken syntax
        s.finish("Fixed add."),
        s.edit(project / "calc.py", "return (a + b", "return a + b"),       # fixed during the review
        s.finish("Fixed add.\nREVIEW: fixed a missing parenthesis in calc.py"),
    ], ui, self_review=True, autonomous=True)
    report = sess.submit("fix add")
    assert ui.prompts == []
    assert report.outcome is Outcome.VERIFIED
    assert "Python syntax error" in _sent(sess) and "fix them first" in _sent(sess)


def test_no_changes_means_no_review(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [s.view(project / "calc.py"), s.finish("add() subtracts; it should add.")],
                        ui, self_review=True)
    report = sess.submit("what's wrong with add?")
    assert report.outcome is Outcome.DONE and "[grid][review]" not in ui.text


def test_review_can_be_turned_off(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [s.edit(project / "calc.py", "a - b", "a + b"), s.finish("Fixed.")],
                        ui, self_review=False)
    assert sess.submit("fix add").outcome is Outcome.VERIFIED and "[grid][review]" not in ui.text


def test_each_task_gets_its_own_review(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [
        s.edit(project / "calc.py", "a - b", "a + b"), s.finish("Fixed add."), s.finish("Fixed add.\nREVIEW: ok"),
        s.edit(project / "calc.py", "a * b", "b * a"), s.finish("Swapped."), s.finish("Swapped.\nREVIEW: ok"),
    ], ui, self_review=True)
    assert sess.submit("fix add").outcome is Outcome.VERIFIED
    assert sess.submit("swap mul").outcome is Outcome.VERIFIED
    assert ui.text.count("[grid][review]") == 2


# ---------------------------------------------------------------- quick checks block "done"

def test_broken_file_blocks_done_even_without_review(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    (project / "config.json").write_text('{"mode": "add"}\n')
    sess = make_session(project, [
        s.edit(project / "calc.py", "a - b", "a + b"),
        s.edit(project / "config.json", '"add"}', '"add",}'),
        s.finish("Fixed."),
        s.edit(project / "config.json", '"add",}', '"add"}'),
        s.finish("Fixed the JSON too."),
    ], ui, self_review=False)
    report = sess.submit("fix add")
    assert report.outcome is Outcome.VERIFIED
    assert "config.json line 1: not valid JSON" in ui.text
    assert json.loads((project / "config.json").read_text()) == {"mode": "add"}


def test_broken_file_left_broken_is_unverified(project):
    s = Script()
    ui = ScriptedUI(interactive=False)
    sess = make_session(project, [
        s.edit(project / "calc.py", "return a - b", "return (a + b"),
        s.finish("Done."), s.finish("Done."), s.finish("Done."),
    ], ui, self_review=False)
    assert sess.submit("fix add").outcome is Outcome.UNVERIFIED
