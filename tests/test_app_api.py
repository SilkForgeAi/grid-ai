"""The Grid app's API: security, projects, files, a full agent task through the
websocket (scripted model), approvals, plugins, models, schedules, settings."""

from __future__ import annotations

import json
import sys
import time

import pytest

pytest.importorskip("openhands.sdk.testing")
from openhands.sdk.llm import Message, MessageToolCall, TextContent  # noqa: E402
from openhands.sdk.testing import TestLLM  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from grid.config import GridConfig  # noqa: E402
from grid.server.api import create_app  # noqa: E402
from grid.server.runtime import Runtime, parse_options  # noqa: E402

PORT = 8765
TOKEN = "test-token-123"
BASE = f"http://127.0.0.1:{PORT}"
H = {"X-Grid": "1"}
PYTEST = f"{sys.executable} -m pytest -q -p no:cacheprovider"


def turn(i, name, args, risk="LOW", conf=0.9):
    if risk and name not in ("finish", "think"):
        args = {**args, "security_risk": risk}
    return Message(role="assistant", content=[TextContent(text=f"step\nCONFIDENCE: {conf}")],
                   tool_calls=[MessageToolCall(id=f"c{i}", name=name, arguments=json.dumps(args), origin="completion")])


class Script:
    def __init__(self):
        self.messages = []

    def __call__(self):
        return TestLLM.from_messages(list(self.messages))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gridhome"))
    # scheduled runs auto-detect `python -m pytest`; make that the test interpreter
    import os

    monkeypatch.setenv("PATH", os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"])
    script = Script()

    def config_factory():
        return GridConfig(condense_context=False, load_user_skills=False, verify_command=PYTEST, self_review=False)

    runtime = Runtime(llm_factory=script, persist=False, config_factory=config_factory)
    app = create_app(token=TOKEN, port=PORT, runtime=runtime)
    client = TestClient(app, base_url=BASE)
    r = client.get(f"/?token={TOKEN}", follow_redirects=False)
    assert r.status_code == 303 and "grid_token" in r.headers["set-cookie"]
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=strict" in r.headers["set-cookie"].lower()
    # TestClient's websocket session doesn't match host-scoped cookies; a browser does.
    client.cookies.clear()
    client.cookies.set("grid_token", TOKEN)
    return client, script, tmp_path, runtime


def make_project(client, tmp_path, name="demo", template="python"):
    r = client.post("/api/projects", json={"name": name, "location": str(tmp_path / "projects"),
                                           "template": template}, headers=H)
    assert r.status_code == 200, r.text
    return r.json()["project"]


def test_learning_starters_are_discoverable_and_creatable(env):
    client, _, tmp_path, _ = env
    state = client.get("/api/state").json()
    assert {item["id"] for item in state["starters"]} == {"tiny-arcade", "story-lab", "pixel-postcard"}
    for item in state["starters"]:
        assert item["id"] in state["templates"]
        project = make_project(client, tmp_path, name=item["id"], template=item["id"])
        from pathlib import Path

        assert (Path(project["path"]) / "main.py").is_file()


def wait_idle(runtime, pid, timeout=30):
    rt = runtime.peek(pid)
    deadline = time.time() + timeout
    while rt.running and time.time() < deadline:
        time.sleep(0.05)
    assert not rt.running


# ---------------------------------------------------------------- security

def test_requires_cookie_header_and_host(env):
    client, *_ = env
    anon = TestClient(client.app, base_url=BASE)
    assert anon.get("/api/state").status_code == 401
    assert anon.get("/").status_code == 401
    assert anon.get("/?token=wrong").status_code == 401
    assert client.get("/api/state").status_code == 200
    # state change without the X-Grid header is refused (cross-site forms can't add it)
    assert client.post("/api/projects/open", json={"path": "/tmp"}).status_code == 403
    evil = TestClient(client.app, base_url="http://evil.example:8765")
    evil.cookies.set("grid_token", TOKEN)
    assert evil.get("/api/state").status_code == 403


def test_websocket_checks_origin(env, tmp_path):
    client, *_ = env
    p = make_project(client, tmp_path)
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/projects/{p['id']}/events", headers={"origin": "http://evil.example", "host": f"127.0.0.1:{PORT}"}) as ws:
            ws.receive_json()


# ---------------------------------------------------------------- projects & files

def test_projects_and_files(env, tmp_path):
    client, _, tmp, _ = env
    p = make_project(client, tmp)
    pid = p["id"]
    names = [e["name"] for e in client.get(f"/api/projects/{pid}/tree").json()["entries"]]
    assert {"demo", "tests", "GRID.md", "README.md"} <= set(names)
    assert client.post(f"/api/projects/{pid}/files/mkdir", json={"path": "src/util"}, headers=H).json()["ok"]
    assert client.post(f"/api/projects/{pid}/files/new", json={"path": "src/util/a.py"}, headers=H).json()["ok"]
    assert client.put(f"/api/projects/{pid}/file", json={"path": "src/util/a.py", "text": "x = 1\n"}, headers=H).json()["ok"]
    assert client.get(f"/api/projects/{pid}/file", params={"path": "src/util/a.py"}).json()["text"] == "x = 1\n"
    assert client.post(f"/api/projects/{pid}/files/rename", json={"path": "src/util/a.py", "to": "src/util/b.py"},
                       headers=H).json()["ok"]
    r = client.post(f"/api/projects/{pid}/files/delete", json={"path": "src/util/b.py"}, headers=H).json()
    assert "trash" in r["trashed_to"]
    # escapes are refused
    for bad in ("../outside.txt", "/etc/passwd", "src/../../x"):
        assert client.get(f"/api/projects/{pid}/file", params={"path": bad}).status_code == 400
        assert client.put(f"/api/projects/{pid}/file", json={"path": bad, "text": "x"}, headers=H).status_code == 400
    # user edits are checkpointed (undoable)
    cps = client.get(f"/api/projects/{pid}/checkpoints").json()["checkpoints"]
    assert any("you edited" in c["label"] for c in cps)
    # duplicate project
    assert client.post("/api/projects", json={"name": "demo", "location": str(tmp / "projects")}, headers=H).status_code == 400
    # open existing / forget
    other = tmp / "elsewhere"
    other.mkdir()
    opened = client.post("/api/projects/open", json={"path": str(other)}, headers=H).json()["project"]
    assert client.delete(f"/api/projects/{opened['id']}", headers=H).json()["ok"]
    assert other.exists()


# ---------------------------------------------------------------- agent

def _calc_project(client, tmp):
    p = make_project(client, tmp, name="calc", template="empty")
    pid = p["id"]
    client.put(f"/api/projects/{pid}/file", json={"path": "calc.py", "text": "def add(a, b):\n    return a - b\n"}, headers=H)
    client.put(f"/api/projects/{pid}/file", json={"path": "test_calc.py",
               "text": "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"}, headers=H)
    return p


def test_task_streams_events_and_verifies(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    path = p["path"]
    script.messages = [
        turn(1, "terminal", {"command": PYTEST}),
        turn(2, "file_editor", {"command": "str_replace", "path": f"{path}/calc.py", "old_str": "a - b", "new_str": "a + b"}),
        turn(3, "finish", {"message": "Fixed add."}),
    ]
    with client.websocket_connect(f"/api/projects/{p['id']}/events", headers={"origin": BASE, "host": f"127.0.0.1:{PORT}"}) as ws:
        assert client.post(f"/api/projects/{p['id']}/tasks", json={"text": "fix add"}, headers=H).json()["ok"]
        seen = []
        while True:
            ev = ws.receive_json()
            seen.append(ev)
            if ev["type"] == "outcome":
                break
    types = [e["type"] for e in seen]
    assert "user" in types and "action" in types and "observation" in types
    outcome = next(e for e in seen if e["type"] == "outcome")
    assert outcome["outcome"] == "verified"
    assert any(e["type"] == "agent" and "Fixed add" in e["text"] for e in seen)
    diff = client.get(f"/api/projects/{p['id']}/diff").json()
    assert "+    return a + b" in diff["diff"]
    wait_idle(runtime, p["id"])


def test_approval_round_trip_and_undo(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    (tmp / "projects" / "calc" / "build").mkdir()
    script.messages = [turn(1, "terminal", {"command": "rm -rf build"}), turn(2, "finish", {"message": "ok"})]
    pid = p["id"]
    client.post(f"/api/projects/{pid}/tasks", json={"text": "clean"}, headers=H)
    deadline = time.time() + 20
    pending = []
    while time.time() < deadline and not pending:
        pending = client.get(f"/api/projects/{pid}/session").json()["pending"]
        time.sleep(0.05)
    assert pending and "[n]o" in pending[0]["prompt"]
    assert {o["key"] for o in pending[0]["options"]} >= {"y", "n", "q"}
    assert "a" not in {o["key"] for o in pending[0]["options"]}       # RED: no "always"
    assert client.post(f"/api/projects/{pid}/answer", json={"id": pending[0]["id"], "text": "n"}, headers=H).json()["ok"]
    wait_idle(runtime, pid)
    assert (tmp / "projects" / "calc" / "build").exists()
    r = client.post(f"/api/projects/{pid}/undo", json={}, headers=H)
    assert r.status_code == 200


def test_autonomous_requires_confirmation(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    pid = p["id"]
    assert client.post(f"/api/projects/{pid}/autonomous", json={"on": True}, headers=H).status_code == 400
    assert client.post(f"/api/projects/{pid}/autonomous", json={"on": True, "allow": ["credentials"], "confirm": "yes"},
                       headers=H).status_code == 400
    r = client.post(f"/api/projects/{pid}/autonomous", json={"on": True, "allow": ["push"], "confirm": "yes"}, headers=H)
    assert r.status_code == 200 and "AUTONOMOUS" in r.json()["description"]
    st = client.get(f"/api/projects/{pid}/session").json()
    assert st["autonomous"] and st["allow"] == ["push"]


def test_stop_cancels_a_waiting_question(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    pid = p["id"]
    script.messages = [turn(1, "terminal", {"command": "git push"}), turn(2, "finish", {"message": "x"})]
    client.post(f"/api/projects/{pid}/tasks", json={"text": "ship"}, headers=H)
    deadline = time.time() + 20
    while time.time() < deadline and not client.get(f"/api/projects/{pid}/session").json()["pending"]:
        time.sleep(0.05)
    client.post(f"/api/projects/{pid}/stop", json={}, headers=H)
    wait_idle(runtime, pid)
    assert client.post(f"/api/projects/{pid}/tasks", json={"text": ""}, headers=H).status_code == 400


def test_plugin_command_runs_from_the_app(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    pid = p["id"]
    cat = client.get("/api/plugins/catalog").json()["plugins"]
    assert {"teach", "git-workflow", "python-quality", "docs-writer", "web-fetch"} <= {c["name"] for c in cat}
    prev = client.post("/api/plugins/preview", json={"source": "builtin:web-fetch"}, headers=H).json()["plugin"]
    assert prev["mcp"]["fetch"].startswith("runs `uvx")
    assert client.post("/api/plugins/install", json={"source": "builtin:teach"}, headers=H).status_code == 200
    cmds = [c["slash"] for c in client.get(f"/api/projects/{pid}/commands").json()["commands"]]
    assert "/teach:explain" in cmds
    script.messages = [turn(1, "finish", {"message": "Here is how add works."})]
    client.post(f"/api/projects/{pid}/tasks", json={"text": "/teach:explain the add function"}, headers=H)
    wait_idle(runtime, pid)
    events = runtime.peek(pid).bus.since(0)
    assert any(e["type"] == "note" and "/teach:explain" in e["text"] for e in events)
    # the LLM received the expanded command text
    sent = json.dumps([str(e) for e in runtime.peek(pid).session.conversation.state.events])
    assert "Explain how the add function works" in sent
    assert client.post("/api/plugins/teach/enable", json={"enabled": False}, headers=H).json()["ok"]
    assert "/teach:explain" not in [c["slash"] for c in client.get(f"/api/projects/{pid}/commands").json()["commands"]]
    assert client.delete("/api/plugins/teach", headers=H).json()["ok"]


def test_models_and_settings(env):
    client, script, tmp, runtime = env
    assert client.post("/api/models", json={"name": "local", "model": "ollama/q"}, headers=H).status_code == 200
    assert client.post("/api/models", json={"name": "bad", "model": "x/y", "api_key_env": "sk-123"}, headers=H).status_code == 400
    data = client.get("/api/models").json()
    assert data["default"] == "local" and data["profiles"][0]["local"]
    s = client.put("/api/settings", json={"depth": "beginner", "step_budget": 10}, headers=H).json()
    assert s["depth"] == "beginner" and s["step_budget"] == 10
    assert client.put("/api/settings", json={"depth": "wizard"}, headers=H).status_code == 400
    # model test runs as a background job (scripted model -> no network)
    script.messages = [
        turn(1, "terminal", {"command": "sed -i.bak 's/a - b/a + b/' calc.py"}),
        turn(2, "finish", {"message": "fixed"}),
    ]
    jid = client.post("/api/models/local/test", json={}, headers=H).json()["job"]
    deadline = time.time() + 60
    job = {}
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{jid}").json()
        if job["status"] != "running":
            break
        time.sleep(0.1)
    assert job["status"] == "done", job
    assert job["result"]["verdict"] in ("ready", "usable")


def test_schedules_api(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    r = client.post("/api/schedules", json={"name": "nightly", "project": p["id"], "prompt": "fix add",
                                            "cron": "@daily"}, headers=H)
    assert r.status_code == 200, r.text
    sid = r.json()["schedule"]["id"]
    assert client.post("/api/schedules", json={"name": "bad", "project": p["id"], "prompt": "x", "cron": "61 * * * *"},
                       headers=H).status_code == 400
    script.messages = [
        turn(1, "file_editor", {"command": "str_replace", "path": f"{p['path']}/calc.py", "old_str": "a - b", "new_str": "a + b"}),
        turn(2, "finish", {"message": "fixed"}),
        # scheduled runs follow Settings, so the consistency review round happens here too
        turn(3, "finish", {"message": "fixed\nREVIEW: no issues found"}),
    ]
    jid = client.post(f"/api/schedules/{sid}/run", json={}, headers=H).json()["job"]
    deadline = time.time() + 60
    while time.time() < deadline and client.get(f"/api/jobs/{jid}").json()["status"] == "running":
        time.sleep(0.1)
    runs = client.get(f"/api/schedules/{sid}/runs").json()["runs"]
    assert runs and runs[0]["outcome"] == "verified", (runs, client.get(f"/api/schedules/{sid}/log").json()["text"])
    assert "scheduled run" in client.get(f"/api/schedules/{sid}/log").json()["text"]
    assert client.get("/api/schedules").json()["schedules"][0]["last_outcome"] == "verified"
    assert client.delete(f"/api/schedules/{sid}", headers=H).json()["ok"]


def test_memory_api(env):
    client, script, tmp, runtime = env
    from grid.memory import Episode, MemoryStore

    p = _calc_project(client, tmp)
    MemoryStore.for_workspace(p["path"]).add(Episode(error_signature="x", lesson="y"))
    eps = client.get(f"/api/projects/{p['id']}/memory").json()["episodes"]
    assert len(eps) == 1
    assert client.delete(f"/api/projects/{p['id']}/memory/0", headers=H).json()["ok"]
    assert client.get(f"/api/projects/{p['id']}/memory").json()["episodes"] == []


def test_parse_options():
    keys = [o["key"] for o in parse_options("Run this? [y]es / [n]o / [a]lways allow YELLOW this session / [q]uit: ")]
    assert keys == ["y", "n", "a", "q"]


def test_file_at_and_revert_one_file(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    pid = p["id"]
    start = client.get(f"/api/projects/{pid}/checkpoints").json()["checkpoints"][0]["id"]
    client.put(f"/api/projects/{pid}/file", json={"path": "calc.py", "text": "def add(a, b):\n    return a + b\n"}, headers=H)
    client.put(f"/api/projects/{pid}/file", json={"path": "new.py", "text": "x = 1\n"}, headers=H)
    before = client.get(f"/api/projects/{pid}/file-at", params={"ref": start, "path": "calc.py"}).json()
    assert before["exists"] and "a - b" in before["text"]
    assert client.get(f"/api/projects/{pid}/file-at", params={"ref": start, "path": "new.py"}).json()["exists"] is False
    assert client.get(f"/api/projects/{pid}/file-at", params={"ref": start, "path": "../x"}).status_code == 400
    r = client.post(f"/api/projects/{pid}/files/revert", json={"path": "calc.py", "ref": start}, headers=H).json()
    assert r["result"] == "restored"
    assert "a - b" in client.get(f"/api/projects/{pid}/file", params={"path": "calc.py"}).json()["text"]
    assert "x = 1" in client.get(f"/api/projects/{pid}/file", params={"path": "new.py"}).json()["text"]   # untouched
    r = client.post(f"/api/projects/{pid}/files/revert", json={"path": "new.py", "ref": start}, headers=H).json()
    assert r["result"] == "removed"


def test_terminal_websocket_runs_a_shell(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    hdrs = {"origin": BASE, "host": f"127.0.0.1:{PORT}"}
    with client.websocket_connect(f"/api/projects/{p['id']}/pty?cols=80&rows=24", headers=hdrs) as ws:
        ws.send_text(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
        ws.send_text(json.dumps({"type": "input", "data": "echo grid-$((6*7)) && pwd\n"}))
        out = ""
        deadline = time.time() + 15
        while time.time() < deadline and "grid-42" not in out:
            msg = json.loads(ws.receive_text())
            if msg["type"] == "output":
                out += msg["data"]
        assert "grid-42" in out and "calc" in out
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/projects/{p['id']}/pty", headers={"origin": "http://evil.example", "host": f"127.0.0.1:{PORT}"}) as ws:
            ws.receive_text()


def test_persona_api(env):
    client, *_ = env
    st = client.get("/api/persona").json()
    assert st["effective"] == "teacher" and st["needs_age_check"]
    assert client.post("/api/persona", json={"persona": "grid"}, headers=H).status_code == 403
    assert client.post("/api/persona", json={"age": "adult"}, headers=H).json()["effective"] == "grid"
    assert client.post("/api/persona", json={"persona": "teacher"}, headers=H).json()["effective"] == "teacher"
    assert client.post("/api/persona", json={"age": "minor"}, headers=H).json()["minor_lock"]
    assert client.post("/api/persona", json={"persona": "grid"}, headers=H).status_code == 403
    assert client.get("/api/state").json()["persona"]["effective"] == "teacher"
    cmds = [c["slash"] for c in client.get(f"/api/projects/{make_project(client, env[2])['id']}/commands").json()["commands"]]
    assert {"/learn", "/hint", "/check", "/next", "/solution", "/quiz"} <= set(cmds)


def test_quick_open_search_and_replace(env):
    client, script, tmp, runtime = env
    p = _calc_project(client, tmp)
    pid = p["id"]
    files = client.get(f"/api/projects/{pid}/files-index").json()["files"]
    assert "calc.py" in files and "GRID.md" in files
    r = client.post(f"/api/projects/{pid}/search", json={"query": "def add"}, headers=H).json()
    assert r["matches"] == 1 and r["results"][0]["path"] == "calc.py"
    assert client.post(f"/api/projects/{pid}/search", json={"query": "(", "regex": True}, headers=H).status_code == 400
    assert client.post(f"/api/projects/{pid}/search", json={"query": "x"}).status_code == 403      # no X-Grid
    before = len(client.get(f"/api/projects/{pid}/checkpoints").json()["checkpoints"])
    r = client.post(f"/api/projects/{pid}/replace", json={"query": "add", "word": True, "case": True, "replace": "plus"}, headers=H).json()
    assert r["replacements"] == 3 and set(r["files_changed"]) == {"calc.py", "test_calc.py"}
    assert "def plus" in client.get(f"/api/projects/{pid}/file", params={"path": "calc.py"}).json()["text"]
    cps = client.get(f"/api/projects/{pid}/checkpoints").json()["checkpoints"]
    assert len(cps) >= before + 1 and "replace 'add'" in cps[0]["label"]
    bad = client.post(f"/api/projects/{pid}/replace", json={"query": "plus", "replace": "x", "paths": ["../outside.py"]}, headers=H)
    assert bad.status_code == 400


def test_first_run_setup(env, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client, script, tmp, runtime = env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("GRID_PROFILE", raising=False)
    st = client.get("/api/setup").json()
    assert st["ready"] is False and st["chosen"] is False and st["done"] is False
    assert st["key_env"] == "OPENAI_API_KEY" and any(p["recommended"] for p in st["providers"] if p.get("recommended"))
    assert client.post("/api/setup/choose", json={"provider": "openai"}, headers=H).status_code == 400   # needs a model id
    st = client.post("/api/setup/choose", json={"provider": "openai", "model": "some-model"}, headers=H).json()
    assert st["model"] == "openai/some-model" and st["key_env"] == "OPENAI_API_KEY" and st["chosen"] and not st["ready"]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert client.get("/api/setup").json()["ready"] is True
    from grid.models import ModelStore

    assert ModelStore().default_name() == "openai" and ModelStore().get("openai").api_key_env == "OPENAI_API_KEY"
    script.messages = [Message(role="assistant", content=[TextContent(text="ready")])]
    job = client.post("/api/setup/check", headers=H).json()["job"]
    for _ in range(100):
        j = client.get(f"/api/jobs/{job}").json()
        if j["status"] != "running":
            break
        time.sleep(0.05)
    assert j["status"] == "done" and j["result"]["ok"] and j["result"]["reply"] == "ready"
    assert client.get("/api/setup/ollama", params={"base_url": "http://example.com"}).status_code == 400
    client.post("/api/setup/done", headers=H)
    assert client.get("/api/setup").json()["done"] is True


def test_friendly_errors():
    from grid.onboarding import friendly_error

    class AuthenticationError(Exception):
        pass

    assert "rejected the key" in friendly_error(AuthenticationError("bad"))
    assert "model id" in friendly_error(Exception("Error code: 404 model_not_found"))
    assert "credit" in friendly_error(Exception("429 quota exceeded"))


def test_chats_resume_after_restart_and_memory_api(tmp_path, monkeypatch):
    """Close the app, open it again: the last chat comes back with its history; earlier chats can be reopened."""
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gridhome"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "Downloads").mkdir(parents=True)

    def boot(messages):
        rt = Runtime(llm_factory=lambda: TestLLM.from_messages(list(messages)), persist=True,
                     config_factory=lambda: GridConfig(condense_context=False, load_user_skills=False, verify_command=PYTEST,
                                                                       self_review=False))
        c = TestClient(create_app(token=TOKEN, port=PORT, runtime=rt), base_url=BASE)
        c.cookies.set("grid_token", TOKEN)
        return c, rt

    finish = lambda msg: Message(role="assistant", content=[TextContent(text=msg)],  # noqa: E731
                                 tool_calls=[MessageToolCall(id="f1", name="finish", arguments=json.dumps({"message": msg}), origin="completion")])
    client, rt = boot([finish("Python lists hold items in order.")])
    p = make_project(client, tmp_path, name="notes", template="empty")
    pid = p["id"]
    client.post(f"/api/projects/{pid}/tasks", json={"text": "what is a python list?"}, headers=H)
    wait_idle(rt, pid)
    first = rt.peek(pid).session.chat_id
    chats = client.get(f"/api/projects/{pid}/chats").json()
    assert chats["current"] == first and chats["chats"][0]["title"] == "what is a python list?"
    # second chat
    client.post(f"/api/projects/{pid}/new-chat", headers=H)
    rt.peek(pid).llm_factory = lambda: TestLLM.from_messages([finish("Dicts map keys to values.")])
    client.post(f"/api/projects/{pid}/tasks", json={"text": "and a dict?"}, headers=H)
    wait_idle(rt, pid)
    second = rt.peek(pid).session.chat_id
    assert second != first and len(client.get(f"/api/projects/{pid}/chats").json()["chats"]) == 2
    rt.shutdown()

    # "restart": a new runtime picks the last chat back up when the project opens
    client2, rt2 = boot([finish("unused")])
    with client2.websocket_connect(f"/api/projects/{pid}/events", headers={"origin": BASE, "host": f"127.0.0.1:{PORT}"}) as ws:
        seen = []
        for _ in range(40):
            ev = ws.receive_json()
            seen.append(ev)
            if ev.get("type") == "agent" and ev.get("replay"):
                break
    assert rt2.peek(pid).session.chat_id == second
    assert any(e.get("type") == "user" and e.get("text") == "and a dict?" for e in seen)
    # reopen the first chat
    assert client2.post(f"/api/projects/{pid}/chats/{first}/open", headers=H).status_code == 200
    assert rt2.peek(pid).session.chat_id == first
    texts = [e.get("text") for e in rt2.peek(pid).bus.since(0) if e.get("replay")]
    assert "what is a python list?" in texts and "Python lists hold items in order." in texts
    assert client2.delete(f"/api/projects/{pid}/chats/{first}", headers=H).status_code == 400   # it's open
    # deleting another chat (the × on its tab) also forgets its saved conversation
    from grid.app import sessions_dir

    sdir = sessions_dir(p["path"])
    assert (sdir / second.replace("-", "")).is_dir()
    assert client2.delete(f"/api/projects/{pid}/chats/{second}", headers=H).status_code == 200
    assert not (sdir / second.replace("-", "")).exists()
    assert [c["id"] for c in client2.get(f"/api/projects/{pid}/chats").json()["chats"]] == [first]
    assert client2.delete(f"/api/projects/{pid}/chats/not-a-chat", headers=H).status_code == 200   # harmless

    # memory facts + search
    r = client2.post("/api/memory/facts", json={"text": "Aaron likes short answers", "scope": "user"}, headers=H).json()
    fid = r["fact"]["id"]
    assert client2.post("/api/memory/facts", json={"text": "password: hunter2", "scope": "user"}, headers=H).status_code == 400
    client2.post("/api/memory/facts", json={"text": "Uses pytest", "scope": "project", "project": pid}, headers=H)
    facts = client2.get("/api/memory/facts", params={"project": pid}).json()
    assert [f["text"] for f in facts["user"]] == ["Aaron likes short answers"] and facts["project"][0]["text"] == "Uses pytest"
    client2.put(f"/api/memory/facts/{fid}", json={"text": "Aaron likes very short answers"}, headers=H)
    hits = client2.get("/api/memory/search", params={"q": "list", "project": pid}).json()["hits"]
    assert any("Python lists hold" in h["text"] for h in hits)   # (the dict chat was deleted above)
    client2.delete(f"/api/memory/facts/{fid}", headers=H)
    assert client2.get("/api/memory/facts").json()["user"] == []

    # Mac access
    dl = tmp_path / "home" / "Downloads"
    assert client2.post("/api/access", json={"path": str(tmp_path / "home" / ".ssh")}, headers=H).status_code in (400, 403)
    assert client2.post("/api/access", json={"path": str(dl)}, headers=H).status_code == 200
    assert client2.get("/api/access").json()["folders"][0]["pretty"] == "~/Downloads"
    (dl / "x.pdf").write_bytes(b"%PDF-1.4 test")
    assert client2.get("/api/download", params={"path": str(dl / "x.pdf")}).status_code == 200
    assert client2.get("/api/download", params={"path": str(tmp_path / "gridhome" / "settings.json")}).status_code == 404
    client2.delete("/api/access", params={"path": str(dl)}, headers=H)
    assert client2.get("/api/download", params={"path": str(dl / "x.pdf")}).status_code == 404
    rt2.shutdown()


def test_message_with_an_image(env):
    import base64
    from io import BytesIO

    from PIL import Image

    client, script, tmp, runtime = env
    p = make_project(client, tmp, name="pics", template="empty")
    pid = p["id"]
    script.messages = [turn(1, "finish", {"message": "A blue square."})]
    buf = BytesIO()
    Image.new("RGB", (20, 20), (0, 0, 255)).save(buf, "PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    assert client.post(f"/api/projects/{pid}/tasks", json={"text": "x", "images": ["data:image/svg+xml;base64,PHN2Zz4="]}, headers=H).status_code == 400
    r = client.post(f"/api/projects/{pid}/tasks", json={"text": "", "images": [url]}, headers=H)
    assert r.status_code == 200, r.text
    wait_idle(runtime, pid)
    user = next(e for e in runtime.peek(pid).bus.since(0) if e["type"] == "user")
    assert user["text"] == "Look at this image." and user["images"][0].startswith("/api/attachments/")
    img = client.get(user["images"][0])
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get("/api/attachments/..%2F..%2Fsettings.json").status_code == 404


def test_stale_editor_save_preserves_newer_disk_content(env):
    client, _, tmp, _ = env
    p = _calc_project(client, tmp)
    url = f"/api/projects/{p['id']}/file"
    old = client.get(url, params={"path": "calc.py"}).json()
    disk = tmp / "projects" / "calc" / "calc.py"
    disk.write_text("# newer external edit\n")
    response = client.put(url, json={"path": "calc.py", "text": "# stale editor\n",
                                    "expected_version": old["version"]}, headers=H)
    assert response.status_code == 409
    assert disk.read_text() == "# newer external edit\n"
    fresh = client.get(url, params={"path": "calc.py"}).json()
    response = client.put(url, json={"path": "calc.py", "text": "# resolved\n",
                                    "expected_version": fresh["version"]}, headers=H)
    assert response.status_code == 200
    assert response.json()["version"] != fresh["version"]


def test_editor_cannot_write_during_scheduled_task(env):
    from grid.execution import project_execution

    client, _, tmp, _ = env
    p = _calc_project(client, tmp)
    with project_execution(p["path"]):
        response = client.put(f"/api/projects/{p['id']}/file",
                              json={"path": "calc.py", "text": "overwrite"}, headers=H)
    assert response.status_code == 409
    assert "return a - b" in (tmp / "projects" / "calc" / "calc.py").read_text()


def test_manual_verification_does_not_race_a_task(env, monkeypatch):
    from grid.execution import project_execution
    from grid.verify import VerifyResult

    client, _, tmp, _ = env
    p = _calc_project(client, tmp)
    called = []
    def check(*args, **kwargs):
        called.append(True)
        return VerifyResult('check', True, 0, '', 0)
    monkeypatch.setattr('grid.verify.run_verify', check)
    with project_execution(p['path']):
        jid = client.post(f"/api/projects/{p['id']}/verify", json={}, headers=H).json()['job']
        deadline = time.time() + 5
        while time.time() < deadline:
            job = client.get(f'/api/jobs/{jid}').json()
            if job['status'] != 'running':
                break
            time.sleep(.02)
        assert job['status'] == 'error', job
        assert 'busy' in job['error'].lower()
    assert not called


def test_execution_mode_is_explicit_in_state(env, monkeypatch):
    client, _, _, _ = env
    monkeypatch.delenv('GRID_RESTRICTED', raising=False)
    assert client.get('/api/state').json()['execution_mode'] == 'trusted-host'
    monkeypatch.setenv('GRID_RESTRICTED', '1')
    assert client.get('/api/state').json()['execution_mode'] == 'restricted'


def test_ui_state_survives_a_new_port(env):
    client, script, tmp, runtime = env
    assert client.get("/api/ui-state").json() == {"values": {}}
    look = '{"color":"#8f3dff","speed":6,"seed":42}'
    assert client.put("/api/ui-state", json={"values": {"grid.particles.look": look}}, headers=H).status_code == 200
    assert client.put("/api/ui-state", json={"values": {"grid.particles.size": "medium"}}, headers=H).status_code == 200
    assert client.get("/api/ui-state").json()["values"] == {"grid.particles.look": look, "grid.particles.size": "medium"}
    # only the particle screen's small values, and only with the app's header
    assert client.put("/api/ui-state", json={"values": {"grid.token": "x"}}, headers=H).status_code == 400
    assert client.put("/api/ui-state", json={"values": {"grid.particles.look": "x" * 5000}}, headers=H).status_code == 400
    assert client.put("/api/ui-state", json={"values": "nope"}, headers=H).status_code == 400
    assert client.put("/api/ui-state", json={"values": {"grid.particles.size": "small"}}).status_code in (400, 403)
    assert client.get("/api/ui-state").json()["values"]["grid.particles.size"] == "medium"
