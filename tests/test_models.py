import http.server
import json
import socket
import threading

import pytest

from grid.models import (
    DEFAULT_MODEL,
    ModelError,
    ModelProfile,
    ModelStore,
    ProbeResult,
    check_endpoint,
    is_local_endpoint,
    looks_like_secret,
    resolve_api_key,
    resolve_profile,
)


@pytest.fixture
def store(tmp_path):
    return ModelStore(tmp_path / "models.json")


def test_add_list_default_remove(store):
    store.add(ModelProfile("local", "ollama/qwen3.6:27b", base_url="http://localhost:11434"))
    store.add(ModelProfile("work", "anthropic/example-model", api_key_env="ANTHROPIC_API_KEY"))
    assert [p.name for p in store.list()] == ["local", "work"]
    assert store.default_name() == "local"          # first one becomes default
    store.set_default("work")
    assert store.default_name() == "work"
    with pytest.raises(ModelError, match="exists"):
        store.add(ModelProfile("work", "openai/gpt-5.5"))
    store.add(ModelProfile("work", "openai/gpt-5.5"), replace=True)
    assert store.get("work").model == "openai/gpt-5.5"
    store.remove("work")
    assert store.default_name() == "local"
    with pytest.raises(ModelError, match="no model profile"):
        store.get("work")


def test_keys_are_never_saved(store):
    with pytest.raises(ModelError, match="NAME of an environment variable"):
        store.add(ModelProfile("bad", "anthropic/example-model", api_key_env="sk-ant-api03-abcdef"))
    store.add(ModelProfile("ok", "anthropic/example-model", api_key_env="ANTHROPIC_API_KEY"))
    text = store.path.read_text()
    assert "ANTHROPIC_API_KEY" in text and "sk-" not in text


@pytest.mark.parametrize("value,secret", [
    ("sk-ant-123", True), ("AIzaSyD-abc", True), ("hf_abc", True),
    ("ANTHROPIC_API_KEY", False), ("MY_KEY", False), ("a" * 40 + "-x", True),
])
def test_looks_like_secret(value, secret):
    assert looks_like_secret(value) is secret


@pytest.mark.parametrize("model,url,local", [
    ("ollama/qwen3.6:27b", None, True),
    ("ollama/qwen3.6:27b", "http://localhost:11434", True),
    ("openai/gpt-oss", "http://192.168.1.20:8000/v1", True),
    ("openai/gpt-oss", "http://mybox.local:8000/v1", True),
    ("openai/gpt-oss", "https://api.together.xyz/v1", False),
    ("anthropic/example-model", None, False),
    ("hosted_vllm/qwen", "http://10.0.0.5:8000", True),
])
def test_is_local_endpoint(model, url, local):
    assert is_local_endpoint(model, url) is local


def test_validation():
    with pytest.raises(ModelError):
        ModelProfile("bad name", "x/y").validate()
    with pytest.raises(ModelError):
        ModelProfile("ok", "x/y", base_url="localhost:11434").validate()
    ModelProfile("ok", "ollama/q", base_url="http://localhost:11434").validate()


def test_resolution_order(store):
    store.add(ModelProfile("local", "ollama/q"))
    store.add(ModelProfile("work", "anthropic/example-model"))
    env = {"LLM_MODEL": "openai/gpt-5.5", "GRID_PROFILE": "work"}
    assert resolve_profile(cli_model="x/y", env=env, store=store)[0].model == "x/y"
    assert resolve_profile(cli_profile="local", env=env, store=store)[0].name == "local"
    assert resolve_profile(env=env, store=store)[0].name == "work"
    assert resolve_profile(env={"LLM_MODEL": "openai/gpt-5.5"}, store=store)[0].model == "openai/gpt-5.5"
    assert resolve_profile(env={}, store=store)[0].name == "local"          # default profile
    assert resolve_profile(env={}, store=ModelStore(store.path.parent / "none.json"))[0].model == DEFAULT_MODEL


def test_api_key_resolution():
    p = ModelProfile("w", "anthropic/example-model", api_key_env="WORK_KEY")
    assert resolve_api_key(p, {"WORK_KEY": "k1", "LLM_API_KEY": "k2"}) == "k1"
    with pytest.raises(ModelError, match=r"\$WORK_KEY"):
        resolve_api_key(p, {"LLM_API_KEY": "k2"})
    q = ModelProfile("q", "anthropic/example-model")
    assert resolve_api_key(q, {"LLM_API_KEY": "k2"}) == "k2"
    assert resolve_api_key(q, {}) is None   # LiteLLM reads ANTHROPIC_API_KEY itself


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_check_endpoint_dead_and_alive():
    dead = ModelProfile("d", "openai/x", base_url=f"http://127.0.0.1:{_free_port()}/v1")
    assert "can't reach" in check_endpoint(dead, timeout=1)

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        alive = ModelProfile("a", "openai/x", base_url=f"http://127.0.0.1:{srv.server_port}/v1")
        assert check_endpoint(alive, timeout=2) is None
    finally:
        srv.shutdown()
    assert check_endpoint(ModelProfile("c", "anthropic/example-model")) is None  # cloud: not pinged


def test_probe_verdicts():
    good = ProbeResult(tool_calls=True, actions=3, risk_labeled=1.0, confidence=1.0, finished=True, verified=True)
    assert good.verdict == "ready" and good.explain() == []
    weak = ProbeResult(tool_calls=True, actions=3, risk_labeled=0.0, confidence=0.0, finished=True, verified=True)
    assert weak.verdict == "usable" and any("UNKNOWN" in n for n in weak.explain())
    none = ProbeResult()
    assert none.verdict == "not-ready" and any("prompted-tools" in n for n in none.explain())
    err = ProbeResult(error="boom")
    assert err.verdict == "not-ready" and not any("prompted-tools" in n for n in err.explain())
    rec = good.to_record()
    assert rec["verdict"] == "ready" and json.dumps(rec)
