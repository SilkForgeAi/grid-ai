"""Mac control (the `computer` tool): permissions per app, apps Grid never touches,
actions that always ask, coordinate scaling - with a fake backend through the
real agent loop, and for real on an X11 display when one is available."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import pytest

pytest.importorskip("openhands.sdk.testing")

from openhands.sdk.llm import Message, MessageToolCall, TextContent  # noqa: E402
from openhands.sdk.testing import TestLLM  # noqa: E402

from grid import computer  # noqa: E402
from grid.config import GridConfig  # noqa: E402
from grid.rules import ActionInfo, GridTier, classify_action  # noqa: E402
from grid.session import UI, GridSession, Outcome  # noqa: E402


class Fake(computer.Backend):
    name = "fake"

    def __init__(self, front="TextEdit", points=(1512, 982), pixels=(3024, 1964)):
        self.front, self.pts, self.px = front, points, pixels
        self.calls = []

    def screen_points(self):
        return self.pts

    def capture(self):
        from io import BytesIO

        from PIL import Image

        out = BytesIO()
        Image.new("RGB", self.px, (240, 240, 240)).save(out, "PNG")
        return out.getvalue()

    def click(self, x, y, button="left", count=1):
        self.calls.append(("click", round(x), round(y), button, count))

    def move(self, x, y):
        self.calls.append(("move", round(x), round(y)))

    def drag(self, *a):
        self.calls.append(("drag", *[round(v) for v in a]))

    def scroll(self, x, y, dx, dy):
        self.calls.append(("scroll", dx, dy))

    def type_text(self, text):
        self.calls.append(("type", text))

    def key(self, combo):
        computer.parse_keys(combo)
        self.calls.append(("key", combo))

    def frontmost_app(self):
        return self.front

    def open_app(self, name):
        self.calls.append(("open", name))
        self.front = name


class UIs(UI):
    def __init__(self, answers=(), interactive=True):
        self.answers, self.prompts, self.lines = list(answers), [], []
        super().__init__(say=self.lines.append, ask=self._ask, interactive=interactive)

    def _ask(self, prompt):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else "n"


n = [0]


def act(**args):
    n[0] += 1
    args.setdefault("security_risk", "LOW")
    return Message(role="assistant", content=[TextContent(text="Next.\nCONFIDENCE: 0.9")],
                   tool_calls=[MessageToolCall(id=f"k{n[0]}", name="computer", arguments=json.dumps(args), origin="completion")])


def fin(msg="done"):
    n[0] += 1
    return Message(role="assistant", content=[TextContent(text=msg)],
                   tool_calls=[MessageToolCall(id=f"k{n[0]}", name="finish", arguments=json.dumps({"message": msg}), origin="completion")])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GRID_HOME", str(tmp_path / "gridhome"))
    ws = tmp_path / "proj"
    ws.mkdir()
    fake = Fake()
    computer.set_backend(fake)
    yield ws, fake
    computer.set_backend(None)


def run(ws, msgs, ui):
    s = GridSession(str(ws), GridConfig(condense_context=False, load_user_skills=False, verify=False, enable_browser=False),
                    ui, llm=TestLLM.from_messages(msgs), persist=False, visualizer=None)
    try:
        return s, s.submit("do it")
    finally:
        s.close()


def obs(s):
    from grid.events import is_observation, observation_text

    return [observation_text(e) for e in s.conversation.state.events if is_observation(e) and e.tool_name == "computer"]


# ------------------------------------------------------------------ pure parts

def test_keys_apps_and_rules():
    assert computer.parse_keys("cmd+shift+t") == (["cmd", "shift"], "t")
    with pytest.raises(ValueError):
        computer.parse_keys("hyper+x")
    assert computer.never_reason("1Password") and computer.never_reason("Terminal") and computer.never_reason("Grid")
    assert computer.never_reason("Safari") is None
    assert computer.fit(3024, 1964) == (1232, 800)

    def cls(action, purpose="", text="", keys=""):
        return classify_action(ActionInfo("computer", f"{action}|{purpose}|{text}|{keys}"))

    assert cls("click", "open the File menu").tier is GridTier.GREEN
    for v in (cls("click", "send the email"), cls("click", "buy now"), cls("click", "delete the folder"),
              cls("key", "", "", "cmd+delete"), cls("type", "enter the password")):
        assert v.tier is GridTier.RED and "computer-sensitive" in v.categories
    assert cls("key", "", "", "cmd+q").tier is GridTier.YELLOW
    assert cls("screenshot", "send").tier is GridTier.GREEN


# ------------------------------------------------------------------ through the agent

def test_asks_for_screen_and_app_then_acts_freely(env):
    ws, fake = env
    ui = UIs(answers=["o", "a"])
    s, r = run(ws, [act(action="screenshot"), act(action="click", x=616, y=400, purpose="open the File menu"),
                    act(action="type", text="Shopping list", purpose="type the title"),
                    act(action="key", keys="cmd+s", purpose="save"), fin()], ui)
    assert r.outcome is Outcome.DONE
    assert len(ui.prompts) == 2 and "see your screen" in ui.prompts[0] and "control TextEdit" in ui.prompts[1]
    # 616 px in a 1232-wide screenshot of a 1512-point screen = 756 points
    assert ("click", 756, 491, "left", 1) in fake.calls
    assert ("type", "Shopping list") in fake.calls and ("key", "cmd+s") in fake.calls
    assert "Front app: TextEdit" in obs(s)[0]
    from grid.access import AppStore

    assert AppStore().allowed("textedit") and not AppStore().allowed(AppStore.SCREEN)   # screen was "once"


def test_never_apps_passwords_and_send_keys(env):
    ws, fake = env
    from grid.access import AppStore

    AppStore().grant(AppStore.SCREEN, always=True)
    AppStore().grant("Messages", always=True)
    fake.front = "1Password"
    ui = UIs(answers=["n"])
    s, _ = run(ws, [act(action="click", x=10, y=10, purpose="open vault"), act(action="open_app", app="Messages", purpose="open Messages"),
                    act(action="type", text="Hunter2!xyz", purpose="type it"),
                    act(action="key", keys="return", purpose="next line"), fin()], ui)
    o = obs(s)
    assert "won't control 1Password" in o[0]
    assert ("open", "Messages") in fake.calls
    assert "never types those" in o[2]
    assert "may send it" in ui.prompts[-1] and "didn't approve" in o[3]
    assert ("key", "return") not in fake.calls


def test_sensitive_purpose_needs_approval_and_headless_never_asks(env):
    ws, fake = env
    from grid.access import AppStore

    AppStore().grant(AppStore.SCREEN, always=True)
    AppStore().grant("TextEdit", always=True)
    ui = UIs(answers=["n"])
    s, _ = run(ws, [act(action="click", x=5, y=5, purpose="send the email", security_risk="LOW"), fin()], ui)
    assert any("Run this?" in p for p in ui.prompts) and not fake.calls
    # headless + an app nobody approved: refused without asking
    fake.front = "Notes"
    ui2 = UIs(interactive=False)
    s2, _ = run(ws, [act(action="click", x=5, y=5, purpose="click the note"), fin()], ui2)
    assert ui2.prompts == [] and "nobody is here to approve" in obs(s2)[0] and not fake.calls


def test_no_backend_means_no_tool(tmp_path, monkeypatch):
    from grid.app import _grid_tool_names

    monkeypatch.setattr(computer, "backend", lambda: None)
    assert "computer" not in _grid_tool_names(GridConfig())


# ------------------------------------------------------------------ for real on X11

@pytest.fixture
def xdisplay():
    if not (shutil.which("Xvfb") and shutil.which("xdotool") and shutil.which("import") and shutil.which("xedit")):
        pytest.skip("needs Xvfb, xdotool, ImageMagick and xedit")
    disp = ":97"
    proc = subprocess.Popen(["Xvfb", disp, "-screen", "0", "1280x800x24"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    old = os.environ.get("DISPLAY")
    os.environ["DISPLAY"] = disp
    computer.set_backend(None)
    yield disp
    computer.set_backend(None)
    proc.terminate()
    if old is None:
        os.environ.pop("DISPLAY", None)
    else:
        os.environ["DISPLAY"] = old


def test_real_x11_click_and_type(xdisplay, tmp_path):
    b = computer.backend()
    assert isinstance(b, computer.XBackend) and b.screen_points() == (1280.0, 800.0)
    f = tmp_path / "note.txt"
    f.write_text("")
    ed = subprocess.Popen(["xedit", "-geometry", "600x400+50+50", str(f)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        before = b.capture()
        b.click(350, 300)                                   # into the text area
        loc = subprocess.run(["xdotool", "getmouselocation"], capture_output=True, text=True).stdout
        assert "x:350 y:300" in loc
        b.type_text("hello grid")
        time.sleep(0.5)
        after = b.capture()
        assert before != after                             # the text showed up on screen
        assert (b.frontmost_app() or "").lower().startswith("xedit")
        png, w, h, ow, oh = computer.scale_png(after)
        assert (w, h) == (1280, 800) and png[:4] == b"\x89PNG"
    finally:
        ed.terminate()


def test_mac_backend_event_sequences(monkeypatch):
    """The ctypes calls the Mac backend makes (macOS itself isn't available here)."""
    import ctypes
    from types import SimpleNamespace

    calls = []

    class Fn:
        def __init__(self, name, ret=None):
            self.name, self.ret = name, ret

        def __call__(self, *a):
            calls.append((self.name, a))
            return self.ret

    class Lib:
        RET = {"CGMainDisplayID": 1, "CGEventCreateMouseEvent": 111, "CGEventCreateKeyboardEvent": 222,
               "CGEventCreateScrollWheelEvent2": 333, "CGPreflightScreenCaptureAccess": True, "AXIsProcessTrusted": False,
               "CGDisplayBounds": SimpleNamespace(size=SimpleNamespace(width=1512.0, height=982.0))}

        def __init__(self, path):
            self.path = path

        def __getattr__(self, name):
            fn = Fn(name, self.RET.get(name))
            setattr(self, name, fn)
            return fn

    monkeypatch.setattr(ctypes, "CDLL", Lib)
    b = computer.MacBackend()
    assert b.permissions() == {"screen": True, "control": False}
    assert b.screen_points() == (1512.0, 982.0)
    calls.clear()
    b.click(100, 200, "left", 2)
    kinds = [a[1] for name, a in calls if name == "CGEventCreateMouseEvent"]
    assert kinds == [5, 1, 2, 1, 2]                       # move, down/up, down/up
    assert ("CGEventSetIntegerValueField", (111, 1, 2)) in calls   # second click has clickState 2
    calls.clear()
    b.key("cmd+shift+t")
    kb = [a for name, a in calls if name == "CGEventCreateKeyboardEvent"]
    assert kb == [(None, 17, True), (None, 17, False)]
    assert ("CGEventSetFlags", (222, 0x100000 | 0x20000)) in calls
    calls.clear()
    b.type_text("héllo 😀\nok")
    uni = [a for name, a in calls if name == "CGEventKeyboardSetUnicodeString"]
    first = list(uni[0][2][: uni[0][1]])
    assert first == [ord(c) for c in "héllo "] + [0xD83D, 0xDE00]     # UTF-16, emoji as a surrogate pair
    assert any(a == (None, 36, True) for name, a in calls if name == "CGEventCreateKeyboardEvent")   # \n -> Return
    posts = [a for name, a in calls if name == "CGEventPost"]
    assert all(a[0] == 0 for a in posts) and [n for n, _ in calls].count("CFRelease") == len(posts)
