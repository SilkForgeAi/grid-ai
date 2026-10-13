"""Local models skip the long hidden reasoning in agent steps unless the profile asks for it."""

from __future__ import annotations

from grid.models import ModelProfile, ModelStore, ollama_llm_settings


def test_local_models_do_not_think_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path))
    monkeypatch.setattr("grid.models.ollama_model_context", lambda *a, **k: None)
    off = ModelProfile("local", "ollama/qwen3:8b", base_url="http://127.0.0.1:9")
    assert ollama_llm_settings(off)[2]["think"] is False
    on = ModelProfile("careful", "ollama/qwen3:8b", base_url="http://127.0.0.1:9", think=True)
    assert ollama_llm_settings(on)[2]["think"] is True


def test_the_switch_is_saved_per_model(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path))
    store = ModelStore()
    store.add(ModelProfile("local", "ollama/qwen3:8b", base_url="http://127.0.0.1:9"))
    assert store.get("local").think is False
    store.set_think("local", True)
    assert store.get("local").think is True
    store.set_think("local", False)
    assert store.get("local").think is False
