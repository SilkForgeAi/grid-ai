"""Browser check of live replies with a fake local model (no API key, no Ollama needed).

    CHROMIUM_PATH=/path/to/chrome python scripts/ui_live_check.py [dark|light] [chat|editor]

A scripted Ollama server streams slowly: a quick reply to "hey" (thinking state,
words appearing, the finished message), then a build request that goes straight to the
agent (reasoning, a tool step, a streamed final answer with code, a table and a
quote). Screenshots of each moment land in ./ui-live-shots-<theme>-<layout>.
"""

import http.server
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ["GRID_HOME"] = str(tmp / "gridhome")
os.environ["HOME"] = str(tmp / "home")
(tmp / "home").mkdir()
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["LOG_LEVEL"] = "WARNING"
for _v in ("LLM_MODEL", "LLM_API_KEY", "GRID_PROFILE", "ANTHROPIC_API_KEY"):
    os.environ.pop(_v, None)

THEME = sys.argv[1] if len(sys.argv) > 1 else "dark"
LAYOUT = sys.argv[2] if len(sys.argv) > 2 else "chat"
DELAY = 0.045
FINAL = (
    "Added `slugify()` to **utils.py** and a test for it.\n\n"
    "```python\nimport re\n\ndef slugify(text: str) -> str:\n    \"\"\"Lowercase, dash-separated, URL-safe.\"\"\"\n"
    "    text = re.sub(r\"[^a-z0-9]+\", \"-\", text.lower())\n    return text.strip(\"-\")\n```\n\n"
    "| Input | Output |\n|---|---|\n| `Hello World` | `hello-world` |\n| `  Grid AI!! ` | `grid-ai` |\n\n"
    "> Why a regex? One pass replaces every run of odd characters with a single dash.\n\nRun `pytest -q` to see it pass."
)
SCRIPT = [
    {"text": "Hey there. Good to see you back.\n\nWhat are we doing today - **building**, **fixing**, or do you want a "
             "quick lesson? A few ideas:\n\n1. Add a `--verbose` flag to the CLI\n2. Write tests for `calc.py`\n"
             "3. Learn how decorators work"},
    {"thinking": "The user wants a slugify helper. I should check what files exist first, then write it with tests.",
     "text": "Let me see what's in the project first.", "tool": ["terminal", {"command": "ls -la", "security_risk": "LOW"}]},
    {"tool": ["finish", {"message": FINAL}]},
]


class FakeOllama(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"models": [{"name": "qwen3:8b"}]}).encode())

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return
        step = SCRIPT.pop(0) if SCRIPT else {"text": "ok"}
        base = {"model": body["model"], "created_at": "2026-01-01T00:00:00Z"}
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        def send(d):
            self.wfile.write((json.dumps({**base, **d}) + "\n").encode())
            self.wfile.flush()

        time.sleep(0.6)
        thinking, text = step.get("thinking", ""), step.get("text", "")
        for i in range(0, len(thinking), 4):
            send({"message": {"role": "assistant", "content": "", "thinking": thinking[i:i + 4]}, "done": False})
            time.sleep(DELAY)
        for i in range(0, len(text), 3):
            send({"message": {"role": "assistant", "content": text[i:i + 3]}, "done": False})
            time.sleep(DELAY)
        msg = {"role": "assistant", "content": ""}
        if "tool" in step:
            msg["tool_calls"] = [{"function": {"name": step["tool"][0], "arguments": step["tool"][1]}}]
        send({"message": msg, "done": True, "done_reason": "stop", "prompt_eval_count": 9, "eval_count": 3})


srv = http.server.HTTPServer(("127.0.0.1", 0), FakeOllama)
OLLAMA = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()

import uvicorn  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from grid.config import GridConfig  # noqa: E402
from grid.models import ModelProfile, ModelStore  # noqa: E402
from grid.persona import PersonaStore  # noqa: E402
from grid.server.api import create_app  # noqa: E402
from grid.server.projects import ProjectRegistry  # noqa: E402
from grid.server.runtime import Runtime  # noqa: E402
from grid.settings import save_settings  # noqa: E402

proj = tmp / "projects" / "demo"
proj.mkdir(parents=True)
(proj / "utils.py").write_text("def add(a, b):\n    return a + b\n")
save_settings({"projects_root": str(tmp / "projects"), "theme": THEME, "setup_done": True, "verify": False})
ModelStore().add(ModelProfile("local", "ollama_chat/qwen3:8b", base_url=OLLAMA), make_default=True)
PersonaStore().answer_age("adult")
PID = ProjectRegistry().open(str(proj)).id
runtime = Runtime(persist=False, config_factory=lambda: GridConfig(
    condense_context=False, load_user_skills=False, verify=False, enable_browser=False, enable_computer=False))
PORT, TOKEN = 8811, "live"
server = uvicorn.Server(uvicorn.Config(create_app(token=TOKEN, port=PORT, runtime=runtime),
                                       host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
time.sleep(1.5)

shots = Path(f"ui-live-shots-{THEME}-{LAYOUT}")
shots.mkdir(exist_ok=True)
errors = []
with sync_playwright() as pw:
    exe = os.environ.get("CHROMIUM_PATH")
    browser = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.add_init_script(f"localStorage.setItem('grid.layout', '{LAYOUT}')")
    page.goto(f"http://127.0.0.1:{PORT}/?token={TOKEN}")
    page.wait_for_timeout(800)
    page.goto(f"http://127.0.0.1:{PORT}/#/p/{PID}")
    page.wait_for_timeout(1500)
    page.screenshot(path=shots / "1-welcome.png")

    box = page.get_by_label("Message Grid")
    box.fill("hey")
    page.keyboard.press("Enter")
    expect(page.locator(".msg-user", has_text="hey")).to_be_visible(timeout=1500)      # shown at once
    expect(page.locator(".msg-agent.live .shimmer")).to_be_visible(timeout=1500)       # and Grid is thinking
    page.screenshot(path=shots / "2-thinking.png")
    expect(page.locator(".msg-agent.live .caret")).to_be_visible(timeout=10000)        # words arrive live
    page.screenshot(path=shots / "3-streaming.png")
    expect(page.locator(".msg-agent:not(.live)", has_text="Learn how decorators")).to_be_visible(timeout=20000)
    assert "<<WORK>>" not in page.locator(".stream").inner_text()
    page.screenshot(path=shots / "4-quick-done.png")

    box.fill("add a slugify helper to utils.py with a test")
    page.keyboard.press("Enter")
    expect(page.locator(".think-peek")).to_be_visible(timeout=10000)                   # reasoning shows while it thinks
    assert page.locator(".think-peek").count() == 1
    page.screenshot(path=shots / "5-agent-thinking.png")
    expect(page.locator(".act")).to_be_visible(timeout=30000)
    expect(page.locator(".narration", has_text="Let me see")).to_be_visible()
    page.screenshot(path=shots / "6-agent-step.png")
    expect(page.locator(".msg-agent.final", has_text="pytest -q")).to_be_visible(timeout=30000)
    expect(page.locator(".msg-agent.final .codeblock .cb-copy")).to_be_visible()
    expect(page.locator(".msg-agent.final table")).to_be_visible()
    assert page.locator(".msg-agent.live").count() == 0
    page.wait_for_timeout(1200)
    page.screenshot(path=shots / "7-done.png")
    browser.close()

if errors:
    sys.exit("page errors: " + "; ".join(errors))
print("UI live check passed - screenshots in", shots)
