from grid.config import GridConfig
from grid.teaching import DepthLevel


def test_defaults_match_roadmap():
    c = GridConfig()
    # Roadmap §4: stop after the same error twice; soft budget ~25.
    assert c.stuck_action_error == 2
    assert c.soft_step_budget == 25
    assert c.confirm_unknown is True
    assert c.depth is DepthLevel.INTERMEDIATE


def test_overrides():
    c = GridConfig(depth=DepthLevel.BEGINNER, confirm_yellow=False)
    assert c.depth is DepthLevel.BEGINNER
    assert c.confirm_yellow is False
