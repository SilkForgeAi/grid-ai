import json

from grid.project import detect_verify_command, load_instructions, project_key


def test_project_key_unique_by_path(tmp_path):
    a, b = tmp_path / "x" / "api", tmp_path / "y" / "api"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert project_key(a) != project_key(b)
    assert project_key(a).startswith("api-")
    assert project_key(tmp_path / "Grid AI") != project_key(tmp_path / "grid-ai")


def test_verify_from_grid_md_wins(tmp_path):
    (tmp_path / "GRID.md").write_text("# rules\nverify: `make check`\n")
    (tmp_path / "test_x.py").write_text("")
    assert detect_verify_command(tmp_path) == "make check"


def test_verify_autodetect(tmp_path):
    assert detect_verify_command(tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "echo \"Error: no test specified\""}}))
    assert detect_verify_command(tmp_path) is None
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}))
    assert detect_verify_command(tmp_path) == "npm test --silent"


def test_verify_python(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("")
    assert detect_verify_command(tmp_path).endswith(" -m pytest -q")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    assert detect_verify_command(tmp_path) == ".venv/bin/python -m pytest -q"


def test_layered_instructions(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("GRID_HOME", str(home))
    (home / "GRID.md").write_text("Use early returns.")
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "GRID.md").write_text("Tests live in tests/.")
    text = load_instructions(ws)
    assert text.index("early returns") < text.index("tests/")
    assert load_instructions(tmp_path / "proj") != ""
