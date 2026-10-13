import json

import pytest

pytest.importorskip("openhands.sdk.plugin")

from grid.plugins import PluginError, PluginManager, builtin_catalog, expand_command  # noqa: E402


def make_plugin(root, name="hello", mcp=None):
    d = root / name
    (d / ".claude-plugin").mkdir(parents=True)
    (d / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name, "version": "0.1.0", "description": "hi"}))
    (d / "commands").mkdir()
    (d / "commands" / "greet.md").write_text("---\ndescription: say hi\n---\nGreet $ARGUMENTS warmly.\n")
    (d / "skills" / "manners").mkdir(parents=True)
    (d / "skills" / "manners" / "SKILL.md").write_text("---\nname: manners\ndescription: be polite\n---\nBe polite.\n")
    if mcp:
        (d / ".mcp.json").write_text(json.dumps({"mcpServers": mcp}))
    return d


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gh"))
    return tmp_path


def test_install_list_enable_remove(home):
    src = make_plugin(home / "src", mcp={"tool": {"command": "echo", "args": ["hi"]}})
    mgr = PluginManager(home)
    prev = mgr.preview(str(src))
    assert prev.skills == ["manners"] and prev.commands[0].slash == "/hello:greet"
    assert prev.mcp == {"tool": "runs `echo hi`"}
    info = mgr.install(str(src))
    assert info.scope == "user" and info.enabled
    with pytest.raises(PluginError, match="already installed"):
        mgr.install(str(src))
    (src / "commands" / "greet.md").write_text("changed at source")
    assert "warmly" in [p for p in mgr.enabled_plugins() if p.name == "hello"][0].commands[0].content  # copied
    mgr.set_enabled("hello", False)
    assert mgr.enabled_plugins() == [] and mgr.commands() == []
    mgr.set_enabled("hello", True)
    mgr.remove("hello")
    assert mgr.list() == []


def test_project_scope_is_separate(home):
    src = make_plugin(home / "src")
    proj = home / "proj"
    proj.mkdir()
    PluginManager(proj).install(str(src), scope="project")
    assert (proj / ".grid" / "plugins" / "hello").is_dir()
    assert [i.scope for i in PluginManager(proj).list()] == ["project"]
    other = home / "other"
    other.mkdir()
    assert PluginManager(other).list() == []


def test_expand_command(home):
    src = make_plugin(home / "src")
    mgr = PluginManager(home)
    mgr.install(str(src))
    plugins = mgr.enabled_plugins()
    out = expand_command("/hello:greet the team", plugins)
    assert "Greet the team warmly." in out and out.startswith("(Running command /hello:greet)")
    assert expand_command("/hello:nope x", plugins) is None
    assert expand_command("fix the bug", plugins) is None


def test_bad_sources(home):
    mgr = PluginManager(home)
    with pytest.raises(PluginError):
        mgr.preview(str(home / "missing"))
    with pytest.raises(PluginError):
        mgr.preview("builtin:nope")


def test_builtin_catalog_is_valid():
    names = {p.name for p in builtin_catalog()}
    assert {"python-quality", "git-workflow", "docs-writer", "teach", "web-fetch"} <= names
    for p in builtin_catalog():
        assert p.description and (p.commands or p.skills or p.mcp)


def test_plugins_reach_the_agent(home):
    from openhands.sdk.testing import TestLLM

    from grid.app import build_agent
    from grid.config import GridConfig

    src = make_plugin(home / "src", mcp={"tool": {"command": "echo"}, "remote": {"url": "https://x.example/mcp"}})
    PluginManager(home).install(str(src))
    agent = build_agent(GridConfig(condense_context=False, load_user_skills=False), str(home),
                        llm=TestLLM.from_messages([]))
    assert "manners" in [s.name for s in agent.agent_context.skills]
    assert set(agent.mcp_config) == {"tool", "remote"}
    local = build_agent(GridConfig(condense_context=False, load_user_skills=False, local_only=True), str(home),
                        llm=TestLLM.from_messages([]))
    assert set(local.mcp_config) == {"tool"}
