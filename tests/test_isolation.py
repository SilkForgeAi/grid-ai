import os
import shutil
import threading

import pytest

from grid.isolation import IsolationError, docker_command, manifest, run_isolated, sync_project


def test_container_configuration_has_no_host_privileges(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
    args = docker_command(str(tmp_path), "grid-test")
    for flag in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pull=never",
    ):
        assert flag in args
    assert "/var/run/docker.sock" not in " ".join(args)
    assert not any("API_KEY" in v for v in args)


def test_missing_runtime_never_falls_back_to_host(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(IsolationError):
        docker_command(str(tmp_path), "grid-test")


def test_import_rejects_symlink_instead_of_following_host_path(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()
    outside = tmp_path / "private"
    outside.write_text("preserve")
    (stage / "escape").symlink_to(outside)
    with pytest.raises(IsolationError, match="symlink"):
        sync_project(stage, original, {})
    assert outside.read_text() == "preserve"


def test_atomic_import_breaks_hardlinks(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()
    outside = tmp_path / "private"
    outside.write_text("preserve")
    os.link(outside, original / "linked")
    (stage / "linked").write_text("preserve")
    before = manifest(stage)
    (stage / "linked").write_text("new project content")
    sync_project(stage, original, before)
    assert outside.read_text() == "preserve"
    assert (original / "linked").read_text() == "new project content"


def test_external_edit_is_not_overwritten(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()
    (original / "a").write_text("old")
    (stage / "a").write_text("old")
    before = manifest(stage)
    (original / "a").write_text("external")
    (stage / "a").write_text("agent")
    with pytest.raises(IsolationError, match="outside"):
        sync_project(stage, original, before)
    assert (original / "a").read_text() == "external"


@pytest.mark.skipif(os.environ.get("GRID_TEST_DOCKER") != "1", reason="requires explicitly enabled Docker integration")
def test_real_container_cannot_read_host_secret_or_reach_network(tmp_path, monkeypatch):
    import shlex

    secret = tmp_path / "outside-secret"
    secret.write_text("synthetic-private-data")
    ws = tmp_path / "project"
    ws.mkdir()
    monkeypatch.setenv("GRID_SYNTHETIC_SECRET", "must-not-enter-container")
    script = (
        f"from pathlib import Path; import os,socket; "
        f"assert not Path({str(secret)!r}).exists(); "
        "assert 'GRID_SYNTHETIC_SECRET' not in os.environ; "
        "assert not Path('/var/run/docker.sock').exists(); "
        "Path('safe.txt').write_text('container worked'); "
        "s=socket.socket(); s.settimeout(1); assert s.connect_ex(('1.1.1.1',443)) != 0"
    )
    code, output = run_isolated({"kind": "terminal", "command": shlex.join(["python", "-c", script])}, str(ws))
    assert code == 0, output
    assert (ws / "safe.txt").read_text() == "container worked"
    assert secret.read_text() == "synthetic-private-data"


@pytest.mark.skipif(os.environ.get("GRID_TEST_DOCKER") != "1", reason="requires explicitly enabled Docker integration")
def test_cancellation_kills_container_without_importing_partial_changes(tmp_path):
    cancel = threading.Event()
    timer = threading.Timer(1, cancel.set)
    timer.start()
    try:
        with pytest.raises(IsolationError):
            run_isolated(
                {"kind": "terminal", "command": "echo partial > partial.txt; sleep 30"}, str(tmp_path), cancel=cancel
            )
    finally:
        timer.cancel()
    assert not (tmp_path / "partial.txt").exists()


@pytest.mark.skipif(os.environ.get("GRID_TEST_DOCKER") != "1", reason="requires explicitly enabled Docker integration")
def test_real_sdk_restricted_edit_and_verification(tmp_path, monkeypatch):
    import json

    from openhands.sdk.llm import Message, MessageToolCall, TextContent
    from openhands.sdk.testing import TestLLM

    from grid.config import GridConfig
    from grid.session import UI, GridSession, Outcome

    monkeypatch.setenv("GRID_RESTRICTED", "1")
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "state"))
    # Policy service behavior is tested separately; this test isolates the SDK adapter.
    monkeypatch.setattr("grid.moderation.policy_reason", lambda *a, **kw: None)
    ws = tmp_path / "project"
    ws.mkdir()
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (ws / "test_calc.py").write_text("from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n")

    def turn(n, name, args):
        if name != "finish":
            args = {**args, "security_risk": "LOW"}
        return Message(
            role="assistant",
            content=[TextContent(text="CONFIDENCE: 0.95")],
            tool_calls=[MessageToolCall(id=f"c{n}", name=name, arguments=json.dumps(args), origin="completion")],
        )

    messages = [
        turn(
            1,
            "file_editor",
            {"command": "str_replace", "path": str(ws / "calc.py"), "old_str": "a - b", "new_str": "a + b"},
        ),
        turn(2, "terminal", {"command": "python -m pytest -q -p no:cacheprovider"}),
        turn(3, "finish", {"message": "Fixed."}),
    ]
    config = GridConfig(condense_context=False, verify_command="python -m pytest -q -p no:cacheprovider")
    session = GridSession(
        str(ws), config, UI(interactive=False), llm=TestLLM.from_messages(messages), persist=False, visualizer=None
    )
    try:
        report = session.submit("Fix addition")
        assert report.outcome is Outcome.VERIFIED, report
        assert "a + b" in (ws / "calc.py").read_text()
        assert session.config.enable_memory is False
        tools = {tool.name for tool in session.conversation.state.agent.tools}
        assert tools == {"grid_isolated_terminal", "grid_isolated_editor"}
    finally:
        session.close()
