"""Browser end-to-end check of the Grid app with a scripted model (no API key).

    pip install playwright && playwright install chromium
    python scripts/ui_smoke.py                 # or CHROMIUM_PATH=/path/to/chrome python scripts/ui_smoke.py

Starts the real server on 127.0.0.1, then drives a real browser through: sign-in,
new project, file tree + editor, a task that ends VERIFIED with a diff, a RED
approval the user rejects, undo, new folder, autonomous mode opt-in, installing
a plugin and its slash command, models, schedules, settings (dark theme).
Screenshots land in ./ui-shots.
"""

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

from browser_cache import preserve_browser_cache

preserve_browser_cache(os.environ, sys.platform)
tmp = Path(tempfile.mkdtemp())
os.environ["GRID_HOME"] = str(tmp / "gridhome")
os.environ["HOME"] = str(tmp / "home")          # Downloads etc. live in a throwaway home
(tmp / "home" / "Downloads").mkdir(parents=True)
os.environ["OPENHANDS_SUPPRESS_BANNER"] = "1"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["OPENAI_API_KEY"] = "test-key"   # so first-run setup sees a usable model
for _v in ("LLM_MODEL", "LLM_API_KEY", "GRID_PROFILE"):
    os.environ.pop(_v, None)
os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]

import uvicorn  # noqa: E402
from openhands.sdk.llm import Message, MessageToolCall, TextContent  # noqa: E402
from openhands.sdk.testing import TestLLM  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from grid.config import GridConfig  # noqa: E402
from grid.server.api import create_app  # noqa: E402
from grid.server.runtime import Runtime  # noqa: E402
from grid.settings import save_settings  # noqa: E402

PY = f"{sys.executable} -m pytest -q -p no:cacheprovider"
projects_root = tmp / "projects"
save_settings({"projects_root": str(projects_root)})
proj = projects_root / "calc"
n = [0]


def turn(name, args, risk="LOW", conf=0.9, thought="Next step."):
    n[0] += 1
    if risk and name not in ("finish", "think"):
        args = {**args, "security_risk": risk}
    return Message(role="assistant", content=[TextContent(text=f"{thought}\nCONFIDENCE: {conf}")],
                   tool_calls=[MessageToolCall(id=f"c{n[0]}", name=name, arguments=json.dumps(args), origin="completion")])


SCRIPT = [
    turn("terminal", {"command": PY}, thought="Run the tests to see what fails."),
    turn("file_editor", {"command": "str_replace", "path": str(proj / "calc.py"), "old_str": "a - b", "new_str": "a + b"},
         thought="add() subtracts; it should add."),
    turn("terminal", {"command": PY}, thought="Confirm the fix."),
    turn("finish", {"message": "Fixed **add**: it subtracted instead of adding. Tests pass."}),
    turn("file_editor", {"command": "view", "path": str(proj / "calc.py")}, thought="Review the change."),
    turn("finish", {"message": "Fixed add. REVIEW: checked addition and its test; no issues found."}),
    turn("terminal", {"command": "rm -rf build"}, thought="Clean the build folder."),
    turn("finish", {"message": "Okay, I left the build folder alone."}),
]
runtime = Runtime(llm_factory=lambda: TestLLM.from_messages(list(SCRIPT)), persist=False,
                  config_factory=lambda: GridConfig(condense_context=False, load_user_skills=False))
PORT, TOKEN = 8799, "uitoken"
MOD = "Meta" if sys.platform == "darwin" else "Control"
server = uvicorn.Server(uvicorn.Config(create_app(token=TOKEN, port=PORT, runtime=runtime),
                                       host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
time.sleep(1.5)

shots = Path("ui-shots")
shots.mkdir(exist_ok=True)
errors = []
with sync_playwright() as pw:
    exe = os.environ.get("CHROMIUM_PATH")
    browser = pw.chromium.launch(executable_path=exe) if exe else pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(f"http://127.0.0.1:{PORT}/?token={TOKEN}")
    expect(page.get_by_role("heading", name="Grid", exact=True, level=1)).to_be_visible()
    page.screenshot(path=shots / "01-home.png")
    # first run: the 18+ question decides Grid's personality
    expect(page.locator(".modal")).to_contain_text("Are you 18 or older?")
    page.screenshot(path=shots / "00-age-gate.png")
    page.locator(".modal").get_by_role("button", name="I'm 18 or older").click()
    expect(page.locator(".toast").first).to_contain_text("Grid voice unlocked")

    page.get_by_role("button", name="New project").first.click()
    page.get_by_label("Name").fill("calc")
    page.get_by_role("button", name="Create").click()
    page.get_by_role("button", name="Files", exact=True).click()
    expect(page.locator(".files .pane-head .title")).to_contain_text("calc")
    expect(page.locator(".welcome h2")).to_contain_text("What will you try in calc?")
    (proj / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (proj / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    page.get_by_title("Refresh").click()
    page.locator(".tree .node", has_text="calc.py").first.click()
    expect(page.locator(".etab.active")).to_contain_text("calc.py")
    expect(page.locator(".ehost .monaco-editor")).to_be_visible(timeout=20000)
    page.wait_for_function("() => window.monaco && monaco.editor.getModels().some(m => m.getValue().includes('return a - b'))")
    # the interactive terminal (bottom panel, editor layout)
    expect(page.locator(".xterm-host .xterm")).to_be_visible(timeout=20000)
    page.locator(".xterm-host").click()
    page.keyboard.type("echo hello-from-grid-$((40+2))\n")
    expect(page.locator(".xterm-host")).to_contain_text("hello-from-grid-42", timeout=15000)
    page.screenshot(path=shots / "02-workspace.png")
    # Cmd/Ctrl+K opens the inline edit box on the current line
    page.locator(".ehost .monaco-editor .view-lines").click()
    page.keyboard.press(f"{MOD}+k")
    expect(page.locator(".inline-edit")).to_be_visible()
    page.keyboard.press("Escape")

    page.get_by_label("Message Grid").fill("Make the failing test pass")
    page.keyboard.press("Enter")
    expect(page.locator(".outcome")).to_contain_text("Checks passed", timeout=60000)
    expect(page.locator(".callout.good")).to_contain_text("Check result")
    assert page.locator(".act").count() >= 3
    page.get_by_role("button", name="Review changes").click()
    expect(page.locator(".review .monaco-diff-editor")).to_be_visible(timeout=20000)
    expect(page.locator(".review-file.active")).to_contain_text("calc.py")
    expect(page.locator(".etab.active")).to_contain_text("Review changes")
    assert "null" not in page.locator(".review-bar").inner_text()
    page.wait_for_timeout(600)
    page.screenshot(path=shots / "03-verified.png")
    # the open editor tab picked up the agent's change from disk
    page.wait_for_function("() => monaco.editor.getModels().some(m => m.uri.path.endsWith('/calc.py') && m.getValue().includes('return a + b'))")
    page.locator(".review-actions").get_by_role("button", name="Keep all").click()
    page.locator(".ins-tabs button", has_text="Changes").click()
    expect(page.locator(".bottom-panel .diffview")).to_contain_text("return a + b")

    (proj / "build").mkdir()
    page.get_by_label("Message Grid").fill("Clean up the build output")
    page.keyboard.press("Enter")
    ask = page.locator(".ask.red")
    expect(ask).to_be_visible(timeout=60000)
    expect(ask).to_contain_text("recursive delete")
    assert ask.get_by_role("button", name="Always").count() == 0
    page.screenshot(path=shots / "04-approval.png")
    ask.get_by_role("button", name="No").click()
    # a task that changed nothing ends with Grid's reply, no result card
    expect(page.locator(".msg-agent", has_text="left the build folder alone")).to_be_visible(timeout=60000)
    assert (proj / "build").exists(), "RED action ran without approval!"
    expect(page.locator(".act.rejected")).to_be_visible()
    assert page.locator(".outcome").count() == 1

    page.get_by_role("button", name="02Code").click()
    page.locator(".ins-tabs button", has_text="Checkpoints").click()
    expect(page.locator(".cp").first).to_be_visible()
    # Focus the guide, then return to the code without losing the task.
    page.get_by_role("button", name="03Understand").click()
    expect(page.locator(".workshop[data-workshop=understand] .stream .outcome").first).to_be_visible()
    page.screenshot(path=shots / "05b-chat-layout.png")
    page.get_by_role("button", name="02Code").click()
    expect(page.locator(".workshop[data-workshop=code]")).to_be_visible()
    page.screenshot(path=shots / "05-checkpoints.png")
    page.locator(".outcome").first.get_by_role("button", name="Undo this task").click()
    page.locator(".modal").get_by_role("button", name="Undo").click()
    expect(page.locator(".callout.info").last).to_contain_text("restored checkpoint", timeout=20000)
    assert "a - b" in (proj / "calc.py").read_text()

    page.get_by_title("New folder").click()
    page.locator(".modal input").fill("src/utils")
    page.locator(".modal").get_by_role("button", name="Create").click()
    expect(page.locator(".tree .node", has_text="utils")).to_be_visible()
    assert (proj / "src" / "utils").is_dir()

    # quick open: fuzzy file match + :line
    page.keyboard.press(f"{MOD}+p")
    expect(page.locator(".palette")).to_be_visible()
    page.keyboard.type("tcalc:4")
    expect(page.locator(".pitem.sel")).to_contain_text("test_calc.py")
    page.screenshot(path=shots / "05c-quick-open.png")
    page.keyboard.press("Enter")
    expect(page.locator(".palette")).to_have_count(0)
    expect(page.locator(".etab.active")).to_contain_text("test_calc.py")
    page.wait_for_function("() => monaco.editor.getEditors().some(e => e.getModel()?.uri.path.endsWith('/test_calc.py') && e.getPosition().lineNumber === 4)")
    # command palette
    page.keyboard.press(f"{MOD}+Shift+p")
    page.keyboard.type("checkpoints")
    page.keyboard.press("Enter")
    expect(page.locator(".ins-tabs button.active")).to_have_text("Checkpoints")
    # search + replace across files
    page.keyboard.press(f"{MOD}+Shift+f")
    expect(page.locator(".search-pane")).to_be_visible()
    page.get_by_label("Search in project").fill("add")
    expect(page.locator(".search-pane .sstatus")).to_contain_text("results in 3 files")   # GRID.md says "Add"
    page.get_by_title("Whole word").click()
    page.get_by_title("Match case").click()
    expect(page.locator(".search-pane .sstatus")).to_contain_text("3 results in 2 files")
    page.locator(".smatch", has_text="def add").click()
    expect(page.locator(".etab.active")).to_contain_text("calc.py")
    page.get_by_title("Toggle replace").click()
    page.get_by_label("Replace with").fill("plus")
    expect(page.locator(".smatch ins").first).to_have_text("plus")
    page.screenshot(path=shots / "05d-search-replace.png")
    page.get_by_role("button", name="Replace all").click()
    page.locator(".modal").get_by_role("button", name="Replace all").click()
    expect(page.locator(".search-pane .sstatus")).to_contain_text("No results", timeout=10000)
    assert "def plus" in (proj / "calc.py").read_text() and "import plus" in (proj / "test_calc.py").read_text()
    page.wait_for_function("() => monaco.editor.getModels().some(m => m.uri.path.endsWith('/calc.py') && m.getValue().includes('def plus'))")
    page.get_by_role("tab", name="Files").click()
    expect(page.locator(".tree")).to_be_visible()

    page.get_by_title("Autonomous mode").click()
    page.locator(".modal label.check", has_text="push").locator("input").check()
    page.locator(".modal").get_by_placeholder("type yes").fill("yes")
    page.screenshot(path=shots / "06-autonomous-modal.png")
    page.locator(".modal").get_by_role("button", name="Turn on").click()
    expect(page.get_by_title("Autonomous mode")).to_contain_text("push")

    page.get_by_role("link", name="Plugins").click()
    expect(page.get_by_role("heading", name="Plugins", exact=True).first).to_be_visible()
    page.get_by_role("button", name="Catalog").click()
    page.locator(".card", has_text="teach").get_by_role("button", name="Install").click()
    expect(page.locator(".modal")).to_contain_text("/teach:explain")
    page.locator(".modal").get_by_role("button", name="Install").click()
    page.get_by_role("button", name="Installed").click()
    expect(page.locator(".card", has_text="teach")).to_be_visible()
    page.screenshot(path=shots / "07-plugins.png")
    page.locator("#project-list a", has_text="calc").click()
    page.get_by_label("Message Grid").fill("/teach")
    expect(page.locator(".slash")).to_contain_text("/teach:explain")
    page.screenshot(path=shots / "08-slash.png")

    page.get_by_role("link", name="Models").click()
    expect(page.get_by_role("heading", name="Models", exact=True).first).to_be_visible()
    page.get_by_label("Name").fill("local")
    page.get_by_label("Model id").fill("ollama/qwen3.6:27b")
    page.get_by_label("Server URL").fill("http://localhost:11434")
    page.get_by_role("button", name="Save model").click()
    expect(page.locator("table.list")).to_contain_text("ollama/qwen3.6:27b")
    page.screenshot(path=shots / "09-models.png")

    page.get_by_role("link", name="Schedules").click()
    expect(page.get_by_role("heading", name="Schedules", exact=True).first).to_be_visible()
    page.get_by_label("Name").fill("nightly")
    page.get_by_label("Task").fill("Run the tests and fix failures")
    page.get_by_role("button", name="Create schedule").click()
    expect(page.locator(".card", has_text="nightly")).to_be_visible()
    page.screenshot(path=shots / "10-schedules.png")

    page.get_by_role("link", name="Memory").click()
    expect(page.get_by_role("heading", name="Memory")).to_be_visible()
    page.get_by_role("link", name="Settings").click()
    expect(page.get_by_role("heading", name="Personality")).to_be_visible()
    page.get_by_role("radio", name="Teacher").check()
    expect(page.locator(".toast").last).to_contain_text("new chats use this voice")
    page.get_by_label("Theme").select_option("dark")
    page.get_by_role("button", name="Save").click()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.locator("#project-list a", has_text="calc").click()
    expect(page.locator(".outcome").first).to_be_visible()
    page.get_by_role("button", name="Files", exact=True).click()
    page.locator(".tree .node", has_text="calc.py").first.click()
    page.wait_for_function("() => document.querySelector('.ehost .monaco-editor')?.classList.contains('vs-dark')")
    page.screenshot(path=shots / "11-dark.png")

    # a new chat: Grid makes a PDF in ~/Downloads, asking for the folder first
    DOC = [turn("create_document", {"format": "pdf", "title": "Git cheat sheet",
                                    "content": "# Git cheat sheet\n\n- `git status`\n- `git commit -m`"}),
           turn("memory", {"command": "remember", "text": "Aaron is learning Git"}),
           turn("finish", {"message": "Saved **Git cheat sheet.pdf** in your Downloads."})]
    for prt in runtime._projects.values():
        prt.llm_factory = lambda: TestLLM.from_messages(list(DOC))
    page.locator("#project-list a", has_text="calc").click()
    page.get_by_title("Autonomous mode").click()          # back to asking first (it was on from earlier)
    expect(page.get_by_title("Autonomous mode")).to_have_attribute("aria-pressed", "false")
    page.get_by_role("button", name="New chat").first.click()
    shot = tmp / "shot.png"
    from PIL import Image

    Image.new("RGB", (64, 40), (30, 120, 200)).save(shot)
    page.get_by_label("Choose images").set_input_files(str(shot))
    expect(page.locator(".img-tray .thumb")).to_have_count(1)
    page.get_by_label("Message Grid").fill("Make me a PDF cheat sheet of Git commands")
    page.keyboard.press("Enter")
    expect(page.locator(".msg-user .msg-imgs img")).to_be_visible(timeout=10000)
    expect(page.locator(".img-tray .thumb")).to_have_count(0)
    ask = page.locator(".ask.access")
    expect(ask).to_contain_text("~/Downloads", timeout=60000)
    page.screenshot(path=shots / "11b-access.png")
    ask.get_by_role("button", name="Once for this chat").click()
    expect(page.locator(".file-card")).to_contain_text("Git cheat sheet.pdf", timeout=30000)
    assert (tmp / "home" / "Downloads" / "Git cheat sheet.pdf").is_file()
    expect(page.locator(".msg-agent", has_text="Saved")).to_be_visible(timeout=30000)
    page.screenshot(path=shots / "11c-document.png")
    with page.expect_download() as dl:
        page.locator(".file-card").get_by_role("link", name="Download").click()
    assert dl.value.suggested_filename == "Git cheat sheet.pdf"
    # chat history lists both chats
    page.get_by_role("button", name="History").click()
    expect(page.locator(".chat-row")).to_have_count(2)
    expect(page.locator(".chat-row.current")).to_contain_text("Make me a PDF cheat sheet")
    page.screenshot(path=shots / "11d-history.png")
    page.locator(".modal").get_by_role("button", name="Close").click()
    # memory page shows what Grid saved
    page.get_by_role("link", name="Memory").click()
    expect(page.locator(".fact")).to_contain_text("Aaron is learning Git")
    page.get_by_label("New memory").fill("Prefers short explanations")
    page.get_by_role("button", name="Remember").click()
    expect(page.locator(".fact").first).to_contain_text("Prefers short explanations")
    page.get_by_role("button", name="Past chats").click()
    page.get_by_label("Search past chats").fill("cheat sheet")
    expect(page.locator(".fact pre.hit").first).to_contain_text("cheat sheet", timeout=10000)
    page.screenshot(path=shots / "11e-memory.png")
    for prt in runtime._projects.values():
        prt.llm_factory = lambda: TestLLM.from_messages(list(SCRIPT))

    # first-run model setup, opened from Settings
    page.get_by_role("link", name="Settings").click()
    assert "null" not in page.locator(".page").inner_text()
    expect(page.get_by_role("heading", name="Grid's browser")).to_be_visible()
    expect(page.get_by_role("heading", name="Mac control")).to_be_visible()
    expect(page.get_by_role("heading", name="Mac access")).to_be_visible()
    page.get_by_role("button", name="Run model setup").click()
    expect(page.locator(".setup")).to_contain_text("Check it works")
    page.locator(".setup").get_by_role("button", name="Run the check").click()
    expect(page.locator(".setup .callout.good")).to_contain_text("It works", timeout=30000)
    page.locator(".setup").get_by_role("button", name="Change model").click()
    page.locator(".pcard", has_text="OpenAI").click()
    page.get_by_label("Model id").fill("test-model")
    os.environ.pop("OPENAI_API_KEY", None)
    page.screenshot(path=shots / "12-setup-choose.png")
    page.locator(".setup").get_by_role("button", name="Continue").click()
    expect(page.locator(".setup .codebox")).to_contain_text("export OPENAI_API_KEY=")
    page.screenshot(path=shots / "13-setup-key.png")
    page.keyboard.press("Escape")
    # with no key for the chosen model, sending a task opens setup instead of failing
    page.locator("#project-list a", has_text="calc").click()
    page.get_by_role("button", name="New chat").first.click()
    expect(page.locator(".setup-nudge")).to_be_visible()
    page.get_by_label("Message Grid").fill("hello")
    page.keyboard.press("Enter")
    expect(page.locator(".setup")).to_be_visible()
    assert page.get_by_label("Message Grid").input_value() == "hello"
    browser.close()

if errors:
    print("BROWSER ERRORS:", *errors, sep="\n  ")
    sys.exit(1)
print("UI smoke test passed - screenshots in", shots.resolve())
