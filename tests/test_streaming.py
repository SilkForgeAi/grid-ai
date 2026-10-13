"""Live replies and quick answers: the token stream the app shows, the quick path for
plain conversation (and its hand-off to the agent), Ollama request settings, reply
clean-up for small models, and reopening a saved chat in a fresh process."""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("openhands.sdk")

from grid.events import clean_reply  # noqa: E402
from grid.stream import StreamRelay, partial_string_field  # noqa: E402

# ------------------------------------------------------------------ pure parts


def test_clean_reply_unwraps_text_tool_calls():
    assert clean_reply('{"message": "Hello! How can I assist you today?"}') == "Hello! How can I assist you today?"
    assert clean_reply('{"name": "finish", "arguments": {"message": "Done."}}') == "Done."
    assert clean_reply('{"name": "finish", "arguments": "{\\"message\\": \\"Hi\\"}"}') == "Hi"
    assert clean_reply('```json\n{"message": "ok"}\n```') == "ok"
    for keep in ("plain words", '{"a": 1}', "{not json}", '{"message": ""}', ""):
        assert clean_reply(keep) == keep


def test_partial_string_field():
    assert partial_string_field('{"mess') is None
    assert partial_string_field('{"message": "') == ""
    assert partial_string_field('{"message": "Hel') == "Hel"
    assert partial_string_field('{"message": "a\\nb \\"q\\" \\u00e9 done", "x": 1}') == 'a\nb "q" é done'
    assert partial_string_field('{"message": "half \\') == "half "          # escape still arriving
    assert partial_string_field('{"message": "x \\u00') == "x "
    assert partial_string_field('{"message": "\\ud83d\\ude00!"}') == "😀!"
    assert partial_string_field('{"message": "\\ud83d') == ""                # half a surrogate pair


def _chunk(rid="r1", content=None, reasoning=None, tool=None):
    tcs = None
    if tool:
        idx, name, args = tool
        tcs = [SimpleNamespace(index=idx, function=SimpleNamespace(name=name, arguments=args))]
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=tcs)
    return SimpleNamespace(id=rid, choices=[SimpleNamespace(delta=delta)])


def test_relay_folds_chunks_into_live_segments():
    out = []
    r = StreamRelay(out.append, interval=0)
    r.on_chunk(_chunk(reasoning="Let me think"))
    r.on_chunk(_chunk(content="Looking at the files.\nCONFIDENCE: 0.9"))
    r.on_chunk(_chunk(tool=(0, "terminal", '{"command": "ls"}')))
    assert [e["phase"] for e in out] == ["thinking", "text", "tool"]
    assert out[1]["text"] == "Looking at the files." and out[2]["tool"] == "terminal"
    assert out[1]["thought_chars"] == len("Let me think")
    r.end()
    # a new model call is a new segment; a finish call streams its message
    for piece in ('{"mes', 'sage": "All ', 'done\\n', 'now"}'):
        r.on_chunk(_chunk(rid="r2", tool=(0, "finish", piece)))
    finals = [e for e in out if e["phase"] == "final"]
    assert finals[-1]["text"] == "All done\nnow"
    assert len({e["sid"] for e in out}) == 2          # segments split on end(), not on chunk ids
    assert all(e["type"] == "stream" for e in out)


def test_relay_throttles():
    out = []
    r = StreamRelay(out.append, interval=10)
    for w in "one two three four".split():
        r.on_chunk(_chunk(content=w + " "))
    assert len(out) == 1                      # same phase within the interval: held back
    r.end()
    assert out[-1]["text"] == "one two three four"


def test_relay_never_raises():
    def boom(_):
        raise RuntimeError("socket gone")

    r = StreamRelay(boom, interval=0)
    r.on_chunk(_chunk(content="hi"))
    r.on_chunk(object())
    r.end()


# ------------------------------------------------------------------ a fake Ollama


class FakeOllama:
    """Scripted /api/chat replies: str = text, dict = a tool call {"name", "arguments"}."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path != "/api/chat":
                    self.send_response(404)
                    self.end_headers()
                    return
                fake.requests.append(body)
                reply = fake.replies.pop(0) if fake.replies else "(no more replies)"
                msg = {"role": "assistant", "content": ""}
                pieces = []
                if isinstance(reply, dict):
                    msg["tool_calls"] = [{"function": {"name": reply["name"], "arguments": reply["arguments"]}}]
                else:
                    pieces = [reply[i:i + 3] for i in range(0, len(reply), 3)]
                base = {"model": body["model"], "created_at": "2026-01-01T00:00:00Z"}
                self.send_response(200)
                if body.get("stream"):
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.end_headers()
                    for p in pieces:
                        self.wfile.write((json.dumps({**base, "message": {"role": "assistant", "content": p}, "done": False}) + "\n").encode())
                    last = {**base, "message": msg, "done": True, "done_reason": "stop", "prompt_eval_count": 9, "eval_count": 3}
                    self.wfile.write((json.dumps(last) + "\n").encode())
                else:
                    if pieces:
                        msg["content"] = reply
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({**base, "message": msg, "done": True, "done_reason": "stop",
                                                 "prompt_eval_count": 9, "eval_count": 3}).encode())

        self.server = http.server.HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def ollama():
    made = []

    def make(replies):
        f = FakeOllama(replies)
        made.append(f)
        return f

    yield make
    for f in made:
        f.close()


def _session(tmp_path, monkeypatch, fake, relay=None, **cfg):
    from grid.config import GridConfig
    from grid.models import ModelProfile, build_llm_from_profile
    from grid.session import UI, GridSession

    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gh"))
    ws = tmp_path / "proj"
    ws.mkdir(exist_ok=True)
    llm = build_llm_from_profile(ModelProfile("local", "ollama/qwen3:8b", base_url=fake.url), num_retries=0)
    said = []
    config = GridConfig(condense_context=False, load_user_skills=False, verify=False, enable_browser=False,
                        enable_computer=False, **cfg)
    s = GridSession(str(ws), config, UI(say=said.append, ask=lambda p: "n"), llm=llm, persist=False,
                    visualizer=None, relay=relay)
    return s, said


def test_quick_reply_streams_and_joins_the_conversation(tmp_path, monkeypatch, ollama):
    from grid.session import Outcome

    fake = ollama(["Hey! What are we building today?"])
    live = []
    relay = StreamRelay(live.append, interval=0)
    s, _ = _session(tmp_path, monkeypatch, fake, relay=relay)
    try:
        r = s.submit("hey")
        assert r.outcome is Outcome.DONE and r.message == "Hey! What are we building today?"
        req = fake.requests[0]
        assert "tools" not in req and req["think"] is False and req["stream"] is True
        assert req["options"]["num_ctx"] >= 8192 and req["keep_alive"]
        assert "<<WORK>>" in req["messages"][0]["content"] and len(req["messages"][0]["content"]) < 12000
        assert req["messages"][-1]["content"].endswith("/no_think")          # Qwen3: no long think for chat
        assert req["options"].get("num_predict") == 1500
        texts = [e["text"] for e in live if e["phase"] == "text"]
        assert texts and texts[-1] == "Hey! What are we building today?" and len(texts) > 1   # it streamed
        kinds = [(type(e).__name__, getattr(e, "source", "")) for e in s.conversation.state.events]
        assert ("MessageEvent", "user") in kinds and ("MessageEvent", "agent") in kinds
        # the next quick reply sees the conversation so far
        fake.replies.append("Sure.")
        s.submit("thanks")
        roles = [m["role"] for m in fake.requests[-1]["messages"]]
        assert roles == ["system", "user", "assistant", "user"]
    finally:
        s.close()


def test_work_goes_to_the_agent_with_its_tools(tmp_path, monkeypatch, ollama):
    from grid.session import Outcome

    fake = ollama(["<<WORK>>", {"name": "finish", "arguments": {"message": "Checked: sunny."}}])
    live = []
    s, _ = _session(tmp_path, monkeypatch, fake, relay=StreamRelay(live.append, interval=0))
    try:
        r = s.submit("what's the weather in Paris right now?")      # reads as chat; the model hands it on
        assert r.outcome is Outcome.DONE and "Checked: sunny." in r.message
        assert len(fake.requests) == 2
        quick, agent = fake.requests
        assert "tools" not in quick
        names = {t["function"]["name"] for t in agent["tools"]}
        assert {"terminal", "file_editor", "finish"} <= names
        assert agent["stream"] is True and agent["options"]["num_ctx"] >= 8192
        assert not any(e["phase"] == "text" and "WORK" in e.get("text", "") for e in live)   # the marker never shows
    finally:
        s.close()


def test_plans_slash_commands_and_quick_off_skip_the_quick_path(tmp_path, monkeypatch, ollama):
    fake = ollama([{"name": "finish", "arguments": {"message": "ok"}}])
    s, _ = _session(tmp_path, monkeypatch, fake, quick_replies=False)
    try:
        s.submit("hey")
        assert len(fake.requests) == 1 and "tools" in fake.requests[0]
    finally:
        s.close()


def test_quick_failure_falls_back_to_the_agent(tmp_path, monkeypatch, ollama):
    from grid import quick

    fake = ollama([{"name": "finish", "arguments": {"message": "fine"}}])
    s, _ = _session(tmp_path, monkeypatch, fake)

    monkeypatch.setattr(quick, "quick_llm", lambda llm: (_ for _ in ()).throw(RuntimeError("no")))
    try:
        r = s.submit("hey")
        assert r.message == "fine"
    finally:
        s.close()


# ------------------------------------------------------------------ resume in a fresh process

def test_saved_chat_reopens_in_a_fresh_process(tmp_path):
    """The confirmation policy a chat was saved with must be known before the state loads."""
    script = r"""
import os, sys
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
from grid.config import GridConfig
from grid.session import UI, GridSession
from openhands.sdk.testing import TestLLM
ws, cid = sys.argv[1], sys.argv[2]
s = GridSession(ws, GridConfig(load_user_skills=False, condense_context=False), UI(say=lambda m: None, interactive=False),
                llm=TestLLM.from_messages([]), resume_id=cid or None, persist=True, visualizer=None)
s.conversation.send_message("hello")
print("ID", s.chat_id)
s.close()
"""
    ws = tmp_path / "p"
    ws.mkdir()
    env = {**os.environ, "GRID_HOME": str(tmp_path / "gh")}
    first = subprocess.run([sys.executable, "-c", script, str(ws), ""], capture_output=True, text=True, env=env, timeout=120)
    cid = [line.split()[1] for line in first.stdout.splitlines() if line.startswith("ID ")][0]
    second = subprocess.run([sys.executable, "-c", script, str(ws), cid.replace("-", "")], capture_output=True,
                            text=True, env=env, timeout=120)
    assert second.returncode == 0, second.stderr[-2000:]
    assert f"ID {cid}" in second.stdout


def test_relay_keeps_one_segment_when_chunk_ids_change():
    out = []
    r = StreamRelay(out.append, interval=0)
    for k, w in enumerate(["Let ", "me ", "see"]):
        r.on_chunk(_chunk(rid=f"chunk-{k}", content=w))      # Ollama gives each chunk its own id
    assert {e["sid"] for e in out} == {out[0]["sid"]} and out[-1]["text"] == "Let me see"


def test_requests_for_work_skip_the_quick_path(tmp_path, monkeypatch, ollama):
    from grid.quick import needs_tools

    for msg in ("option 2. i want a web app that can be shared for everyone to use whoever has the link",
                "build me a rock paper scissors game", "fix the failing test", "make a PDF of my notes",
                "yes", "2", "sure!", "explain how this project is structured", "let's do it"):
        assert needs_tools(msg), msg
    for msg in ("hey", "thanks!", "what is a variable in python? keep it short", "how are you", "lol nice"):
        assert not needs_tools(msg), msg
    fake = ollama([{"name": "finish", "arguments": {"message": "Built it."}}])
    s, _ = _session(tmp_path, monkeypatch, fake)
    try:
        r = s.submit("option 2. i want a web app that can be shared for everyone to use whoever has the link")
        assert r.message == "Built it." and len(fake.requests) == 1 and "tools" in fake.requests[0]
        system = fake.requests[0]["messages"][0]["content"]
        assert "Never answer a build request with only a plan" in system and "GitHub Pages" in system
    finally:
        s.close()
