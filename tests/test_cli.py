import pytest

from grid import cli


def test_threshold_validated_at_boundary():
    with pytest.raises(SystemExit):
        cli._parse_args(["task", "--confidence-threshold", "5"])


def test_flags_map_to_config():
    cfg = cli._config_from(cli._parse_args([
        "task", "--yolo", "--strict-confidence", "--no-verify", "--step-budget", "7", "--plan",
    ]))
    assert cfg.confirm_yellow is False and cfg.strict_confidence and not cfg.verify
    assert cfg.soft_step_budget == 7 and cfg.plan_first


def test_headless_without_task_is_usage_error(capsys):
    assert cli.main(["--headless"]) == 2


def test_checkpoints_subcommand(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    ws = tmp_path / "p"
    ws.mkdir()
    (ws / "a.txt").write_text("1")
    monkeypatch.chdir(ws)
    from grid.checkpoints import CheckpointStore

    s = CheckpointStore(ws)
    s.snapshot("start")
    (ws / "a.txt").write_text("2")
    s.snapshot("edit")
    assert cli.main(["checkpoints"]) == 0
    assert "edit" in capsys.readouterr().out
    assert cli.main(["undo"]) == 0
    assert (ws / "a.txt").read_text() == "1"
    assert cli.main(["diff", "0"]) == 0


class _Report:
    def __init__(self):
        from grid.session import Outcome

        self.outcome = Outcome.VERIFIED
        self.start_checkpoint = None


class _StubSession:
    def __init__(self):
        from grid.config import GridConfig

        self.config = GridConfig()
        self.workspace = "."
        self.checkpoints = None
        self.calls = []

    def submit(self, task, plan=False):
        self.calls.append((task, plan))
        return _Report()

    def undo(self, ref=None):
        self.calls.append(("undo", ref))
        return "restored"


def test_repl_routes_tasks_and_commands(monkeypatch, capsys):
    lines = iter(["fix the bug", "/plan add a flag", "/undo 2", "/help", "/bogus", "/quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(lines))
    stub = _StubSession()
    code = cli._repl(stub, "first task", once=False)
    assert code == 0
    assert stub.calls == [("first task", False), ("fix the bug", False), ("add a flag", True), ("undo", "2")]
    out = capsys.readouterr().out
    assert "/undo [N]" in out and "unknown command /bogus" in out


def test_autonomous_flag_validation():
    assert cli.main(["--allow", "push", "x"]) == 2
    assert cli.main(["--autonomous", "--no-verify", "x"]) == 2
    assert cli.main(["--autonomous", "--allow", "credentials", "x"]) == 2


def test_autonomous_confirmation_requires_typing_yes(capsys):
    assert cli._confirm_autonomous(frozenset(), ask=lambda p: "yes") is True
    assert cli._confirm_autonomous(frozenset(), ask=lambda p: "y") is False
    assert "AUTONOMOUS MODE" in capsys.readouterr().out


def test_auto_repl_command(capsys):
    calls = []

    class S:
        def set_autonomous(self, on, allow=None):
            calls.append((on, allow))

    cli._auto_command(S(), "on --allow push,delete", ask=lambda p: "yes")
    cli._auto_command(S(), "on", ask=lambda p: "no")
    cli._auto_command(S(), "off")
    cli._auto_command(S(), "on --allow root", ask=lambda p: "yes")
    assert calls == [(True, frozenset({"push", "delete"})), (False, None)]
    assert "never be pre-approved" in capsys.readouterr().out


def test_models_subcommands(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    assert cli.main(["models"]) == 0
    assert "no saved profiles" in capsys.readouterr().out
    assert cli.main(["models", "add", "local", "--model", "ollama/q", "--base-url", "http://localhost:11434"]) == 0
    assert cli.main(["models", "add", "work", "--model", "anthropic/example-model",
                     "--key-env", "sk-ant-oops"]) == 2
    assert cli.main(["models", "add", "work", "--model", "anthropic/example-model",
                     "--key-env", "ANTHROPIC_API_KEY"]) == 0
    assert cli.main(["models", "use", "work"]) == 0
    capsys.readouterr()
    assert cli.main(["models", "list"]) == 0
    out = capsys.readouterr().out
    assert "* work" in out and "[local]" in out and "untested" in out
    assert cli.main(["models", "remove", "local"]) == 0
    assert cli.main(["models", "use", "nope"]) == 2


def test_local_only_refuses_cloud_model(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    assert cli.main(["--local-only", "--model", "anthropic/example-model", "--headless", "x"]) == 2
    assert cli.main(["--profile", "missing", "--headless", "x"]) == 2


def test_model_repl_command(tmp_path, monkeypatch, capsys):
    from grid.config import GridConfig
    from grid.models import ModelProfile, ModelStore

    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    ModelStore().add(ModelProfile("local", "ollama/q"))

    class S:
        config = GridConfig(model_profile=ModelProfile("cli", "anthropic/example-model"))

        def switch_model(self, profile):
            return f"now using {profile.model}"

    cli._model_command(S(), "")
    cli._model_command(S(), "local")
    cli._model_command(S(), "missing")
    out = capsys.readouterr().out
    assert "model: anthropic/example-model" in out and "saved profiles: local" in out
    assert "now using ollama/q" in out and "no model profile 'missing'" in out


def test_persona_command_and_first_run_question(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "home"))
    assert cli.main(["persona"]) == 0
    assert "Teacher" in capsys.readouterr().out
    assert cli.main(["persona", "grid"]) == 2            # not before the 18+ answer
    cli.ask_age_once(ask=lambda q: "y")
    assert cli.main(["persona"]) == 0 and "Grid (adult mode)" in capsys.readouterr().out
    cli.ask_age_once(ask=lambda q: (_ for _ in ()).throw(AssertionError("asked twice")))   # only asked once
    assert cli.main(["persona", "minor"]) == 0 and "locked" in capsys.readouterr().out
