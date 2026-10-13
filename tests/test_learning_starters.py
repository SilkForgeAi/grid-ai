import subprocess
import sys

import pytest

from grid.learning import STARTERS
from grid.server.projects import ProjectError, ProjectRegistry


@pytest.mark.parametrize("starter", STARTERS, ids=lambda item: item["id"])
def test_starter_is_runnable_and_checks_real_behavior(tmp_path, starter):
    registry = ProjectRegistry(tmp_path / "registry.json")
    project = registry.create(starter["id"], str(tmp_path / "projects"),
                              template=starter["id"], git_init=False)
    checks = subprocess.run([sys.executable, "-m", "unittest", "discover", "-v"],
                            cwd=project.path, capture_output=True, text=True, timeout=15)
    assert checks.returncode == 0, checks.stderr
    assert "Ran 3 tests" in checks.stderr
    sample_input = {"tiny-arcade": "not a number\n2\n9\n7\n", "story-lab": "forest\n", "pixel-postcard": ""}
    run = subprocess.run([sys.executable, "main.py"], cwd=project.path, input=sample_input[starter["id"]],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip()
    from pathlib import Path

    root = Path(project.path)
    assert starter["challenge"] in (root / "README.md").read_text()
    assert "verify: python -m unittest discover -v" in (root / "GRID.md").read_text()
    if starter["id"] == "pixel-postcard":
        assert (root / "postcard.svg").is_file()


def test_unknown_template_leaves_no_empty_project(tmp_path):
    registry = ProjectRegistry(tmp_path / "registry.json")
    with pytest.raises(ProjectError, match="unknown template"):
        registry.create("example", str(tmp_path / "projects"), template="missing")
    assert not (tmp_path / "projects").exists()


def test_starter_never_overwrites_existing_project(tmp_path):
    existing = tmp_path / "mine"
    existing.mkdir()
    code = existing / "main.py"
    code.write_text("my original work")
    registry = ProjectRegistry(tmp_path / "registry.json")
    with pytest.raises(ProjectError, match="already exists"):
        registry.create("mine", str(tmp_path), template="tiny-arcade")
    assert code.read_text() == "my original work"
