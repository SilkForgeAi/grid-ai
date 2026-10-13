"""The Settings page shapes the agent: check-in steps, depth, verify and plan-first reach new chats
and scheduled runs; what a project picked in its own chat still wins."""

from __future__ import annotations

from grid.server.projects import ProjectRegistry
from grid.server.runtime import Runtime
from grid.settings import save_settings
from grid.teaching import DepthLevel


def test_settings_reach_new_chats(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    (tmp_path / "p").mkdir()
    project = ProjectRegistry().open(str(tmp_path / "p"))
    rt = Runtime(persist=False).get(project)
    assert rt._new_config().soft_step_budget == 25          # the default
    save_settings({"step_budget": 7, "verify": False, "depth": "beginner", "plan_first": True})
    c = rt._new_config()                                    # no restart needed
    assert (c.soft_step_budget, c.verify, c.depth, c.plan_first) == (7, False, DepthLevel.BEGINNER, True)
    rt.chosen["plan_first"] = False                         # picked in this project's chat
    rt.base_config.autonomous = True
    c = rt._new_config()
    assert c.plan_first is False and c.autonomous is True and c.soft_step_budget == 7


def test_a_fixed_test_config_is_left_alone(tmp_path, monkeypatch):
    from grid.config import GridConfig

    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    (tmp_path / "p").mkdir()
    save_settings({"step_budget": 7})
    project = ProjectRegistry().open(str(tmp_path / "p"))
    rt = Runtime(persist=False, config_factory=lambda: GridConfig(soft_step_budget=3)).get(project)
    assert rt._new_config().soft_step_budget == 3


def test_review_and_step_limit_settings(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    (tmp_path / "p").mkdir()
    project = ProjectRegistry().open(str(tmp_path / "p"))
    rt = Runtime(persist=False).get(project)
    c = rt._new_config()
    assert c.self_review is True and c.autonomous_max_steps == 300      # the defaults
    save_settings({"self_review": False, "autonomous_max_steps": 120})
    c = rt._new_config()
    assert c.self_review is False and c.autonomous_max_steps == 120
    for bad in (5, 6000):
        with pytest.raises(ValueError):
            save_settings({"autonomous_max_steps": bad})


def test_autonomy_dialog_shows_the_step_limit():
    from grid.autonomy import describe_mode

    text = describe_mode(frozenset(), 120, True)
    assert "pauses after 120 steps" in text and "re-reads its changes for consistency" in text
    assert "re-reads" not in describe_mode(frozenset(), 120, False)
