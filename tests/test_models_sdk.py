"""BYO-model wiring through the real SDK (scripted model, no network)."""

import json
import sys

import pytest

pytest.importorskip("openhands.sdk.testing")

from openhands.sdk.llm import Message, MessageToolCall, TextContent  # noqa: E402
from openhands.sdk.testing import TestLLM  # noqa: E402

from grid.app import effective_profile  # noqa: E402
from grid.config import GridConfig  # noqa: E402
from grid.models import ModelError, ModelProfile, build_llm_from_profile  # noqa: E402
from grid.probe import format_result, run_probe  # noqa: E402

PYTEST = f"{sys.executable} -m pytest -q -p no:cacheprovider"


def _turn(i, name, args, thought="Next.\nCONFIDENCE: 0.9", risk="LOW"):
    if risk and name not in ("finish", "think"):
        args = {**args, "security_risk": risk}
    return Message(role="assistant", content=[TextContent(text=thought)],
                   tool_calls=[MessageToolCall(id=f"c{i}", name=name, arguments=json.dumps(args),
                                               origin="completion")])


def test_build_llm_from_profile_sets_fields(monkeypatch):
    monkeypatch.setenv("WORK_KEY", "secret-value")
    p = ModelProfile("w", "openai/gpt-oss", base_url="http://localhost:8000/v1",
                     api_key_env="WORK_KEY", native_tool_calling=False)
    llm = build_llm_from_profile(p, num_retries=1)
    assert llm.model == "openai/gpt-oss" and llm.base_url == "http://localhost:8000/v1"
    assert llm.native_tool_calling is False and llm.num_retries == 1
    assert llm.api_key.get_secret_value() == "secret-value"
    assert "secret-value" not in llm.model_dump_json()   # masked when serialized


def test_effective_profile_local_only_and_prompted_tools():
    cloud = GridConfig(model_profile=ModelProfile("c", "anthropic/example-model"), local_only=True)
    with pytest.raises(ModelError, match="off this machine"):
        effective_profile(cloud)
    local = GridConfig(model_profile=ModelProfile("l", "ollama/q"), local_only=True, prompted_tools=True)
    assert effective_profile(local).native_tool_calling is False


def test_probe_on_a_well_behaved_model(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gh"))
    # The probe's workspace path is random, so the edit is a terminal sed.
    script = [
        _turn(1, "terminal", {"command": PYTEST}),
        _turn(2, "terminal", {"command": "sed -i.bak 's/a - b/a + b/' calc.py"}),
        _turn(3, "terminal", {"command": PYTEST}),
        _turn(4, "finish", {"message": "fixed"}),
    ]
    result = run_probe(ModelProfile("t", "test/model"), llm=TestLLM.from_messages(script))
    assert result.verdict == "ready", format_result(ModelProfile("t", "test/model"), result)
    assert result.actions == 3 and result.risk_labeled == 1.0 and result.confidence == 1.0


def test_probe_check_works_without_pytest(tmp_path, monkeypatch):
    # The installed app's engine has no pytest: shadow it with one that always fails.
    fake = tmp_path / "nopytest"
    fake.mkdir()
    (fake / "pytest.py").write_text("raise SystemExit('No module named pytest')\n")
    monkeypatch.setenv("PYTHONPATH", str(fake))
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gh"))
    script = [
        _turn(1, "terminal", {"command": "sed -i.bak 's/a - b/a + b/' calc.py"}),
        _turn(2, "finish", {"message": "fixed"}),
    ]
    result = run_probe(ModelProfile("t", "test/model"), llm=TestLLM.from_messages(script))
    assert result.verified, format_result(ModelProfile("t", "test/model"), result)


def test_probe_flags_a_model_that_skips_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gh"))
    script = [
        _turn(1, "terminal", {"command": "sed -i.bak 's/a - b/a + b/' calc.py"}, thought="fixing", risk=None),
        _turn(2, "finish", {"message": "fixed"}, thought="done"),
    ]
    result = run_probe(ModelProfile("t", "test/model"), llm=TestLLM.from_messages(script))
    # unlabeled -> UNKNOWN; the probe runs unattended, so the action is refused and nothing gets fixed
    assert result.risk_labeled == 0.0 and result.verdict != "ready"


def test_probe_on_a_model_that_never_calls_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gh"))
    script = [Message(role="assistant", content=[TextContent(text="Just change - to + in calc.py.")])]
    result = run_probe(ModelProfile("t", "test/model"), llm=TestLLM.from_messages(script))
    assert result.verdict == "not-ready" and not result.tool_calls


def test_switch_model_mid_session(tmp_path, monkeypatch):
    from grid.session import UI, GridSession

    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gh"))
    ws = tmp_path / "p"
    ws.mkdir()
    sess = GridSession(str(ws), GridConfig(condense_context=False, load_user_skills=False),
                       UI(say=lambda m: None, interactive=False),
                       llm=TestLLM.from_messages([]), persist=False, visualizer=None)
    msg = sess.switch_model(ModelProfile("local", "ollama/qwen3.6:27b", base_url="http://localhost:11434"))
    assert "ollama/qwen3.6:27b" in msg
    llm = sess.conversation.agent.llm
    # Ollama goes through its chat API (real tool calls), with room for Grid's prompt, kept loaded
    assert llm.model == "ollama_chat/qwen3.6:27b"
    assert llm.litellm_extra_body["options"]["num_ctx"] >= 8192 and llm.litellm_extra_body["keep_alive"]
    sess.config.local_only = True
    with pytest.raises(ModelError):
        sess.switch_model(ModelProfile("c", "anthropic/example-model"))


def test_session_files_never_contain_the_key(tmp_path, monkeypatch):
    from grid.app import sessions_dir
    from grid.session import UI, GridSession

    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gh"))
    ws = tmp_path / "p"
    ws.mkdir()
    llm = TestLLM.from_messages([_turn(1, "finish", {"message": "hi"})])
    llm = llm.model_copy(update={"api_key": __import__("pydantic").SecretStr("sk-very-secret-123")})
    sess = GridSession(str(ws), GridConfig(condense_context=False, load_user_skills=False),
                       UI(say=lambda m: None, interactive=False), llm=llm, visualizer=None)
    sess.submit("say hi")
    sess.close()
    blob = "".join(p.read_text(errors="ignore") for p in sessions_dir(str(ws)).rglob("*") if p.is_file())
    assert blob and "sk-very-secret-123" not in blob
