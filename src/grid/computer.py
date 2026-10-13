"""Letting Grid use the Mac: see the screen, click, type, press keys, open apps.

Two backends with the same small interface:
  - MacBackend: CoreGraphics through ctypes (mouse and keyboard events),
    `screencapture` for screenshots and `lsappinfo` / `open` for apps. Needs the
    Accessibility and Screen Recording permissions for Grid (macOS asks).
  - XBackend: xdotool + ImageMagick on Linux/X11 (used to test this on CI).

Safety lives in grid.tools.definitions (per-app permission, apps Grid never
touches, actions that always ask) and grid.rules (sensitive purposes).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

MAX_W, MAX_H = 1280, 800      # what the model sees; coordinates are in this space

# Apps Grid never controls.
NEVER_APPS = {
    "keychain access": "it holds your passwords",
    "passwords": "it holds your passwords",
    "1password": "it holds your passwords", "1password 7": "it holds your passwords",
    "bitwarden": "it holds your passwords", "lastpass": "it holds your passwords",
    "dashlane": "it holds your passwords", "keepassxc": "it holds your passwords", "enpass": "it holds your passwords",
    "securityagent": "that's a system password prompt - type it yourself",
    "loginwindow": "that's the login window",
    "grid": "that's Grid itself - open the app you want me to use first",
    "electron": "that's Grid itself - open the app you want me to use first",
    "terminal": "use Grid's own terminal instead", "iterm2": "use Grid's own terminal instead",
    "warp": "use Grid's own terminal instead", "alacritty": "use Grid's own terminal instead",
    "kitty": "use Grid's own terminal instead", "ghostty": "use Grid's own terminal instead",
    "wezterm": "use Grid's own terminal instead", "hyper": "use Grid's own terminal instead",
}
# Apps where pressing Return/Enter can send something: those keys always ask.
SEND_APPS = {"mail", "messages", "slack", "discord", "whatsapp", "telegram", "signal", "microsoft outlook",
             "microsoft teams", "zoom.us", "facetime", "messenger", "outlook"}
# Apps where every action asks.
ASK_EVERY_TIME_APPS = {"system settings", "system preferences"}


def never_reason(app: str | None) -> str | None:
    return NEVER_APPS.get((app or "").strip().lower())


@dataclass
class Shot:
    png: bytes          # what the model sees (scaled)
    width: int
    height: int


def fit(w: int, h: int) -> tuple[int, int]:
    s = min(MAX_W / w, MAX_H / h, 1.0)
    return max(1, round(w * s)), max(1, round(h * s))


def scale_png(png: bytes) -> tuple[bytes, int, int, int, int]:
    """(scaled png, scaled w, h, original w, h)."""
    from io import BytesIO

    from PIL import Image

    im = Image.open(BytesIO(png))
    im.load()
    ow, oh = im.size
    w, h = fit(ow, oh)
    if (w, h) != (ow, oh):
        im = im.resize((w, h), Image.LANCZOS)
    out = BytesIO()
    im.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue(), w, h, ow, oh


# -- keys ---------------------------------------------------------------------------

MAC_KEYCODES = {
    "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12, "w": 13,
    "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23, "=": 24, "9": 25,
    "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37, "j": 38,
    "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46, ".": 47, "`": 50,
    "return": 36, "enter": 36, "tab": 48, "space": 49, "backspace": 51, "delete": 51, "escape": 53, "esc": 53,
    "forwarddelete": 117, "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101, "f10": 109,
    "f11": 103, "f12": 111,
}
MAC_FLAGS = {"shift": 0x20000, "ctrl": 0x40000, "control": 0x40000, "alt": 0x80000, "option": 0x80000,
             "opt": 0x80000, "cmd": 0x100000, "command": 0x100000, "fn": 0x800000}
X_KEYS = {"return": "Return", "enter": "Return", "tab": "Tab", "space": "space", "backspace": "BackSpace",
          "delete": "BackSpace", "forwarddelete": "Delete", "escape": "Escape", "esc": "Escape", "home": "Home",
          "end": "End", "pageup": "Prior", "pagedown": "Next", "left": "Left", "right": "Right", "up": "Up",
          "down": "Down"}
X_MODS = {"cmd": "super", "command": "super", "ctrl": "ctrl", "control": "ctrl", "alt": "alt", "option": "alt",
          "opt": "alt", "shift": "shift"}


def parse_keys(combo: str) -> tuple[list[str], str]:
    """'cmd+shift+t' -> (['cmd', 'shift'], 't'). Raises ValueError for unknown keys."""
    parts = [p.strip().lower() for p in re.split(r"\s*\+\s*", (combo or "").strip()) if p.strip()]
    if not parts:
        raise ValueError("no key given")
    *mods, key = parts
    for m in mods:
        if m not in MAC_FLAGS:
            raise ValueError(f"unknown modifier {m!r} (use cmd, shift, ctrl, alt)")
    if key not in MAC_KEYCODES:
        raise ValueError(f"unknown key {key!r}")
    return mods, key


# -- backends -----------------------------------------------------------------------

class Backend:
    name = "none"

    def permissions(self) -> dict:
        return {"screen": True, "control": True}

    def screen_points(self) -> tuple[float, float]:
        raise NotImplementedError

    def capture(self) -> bytes:
        raise NotImplementedError

    def click(self, x: float, y: float, button: str = "left", count: int = 1) -> None:
        raise NotImplementedError

    def move(self, x: float, y: float) -> None:
        raise NotImplementedError

    def drag(self, x1: float, y1: float, x2: float, y2: float) -> None:
        raise NotImplementedError

    def scroll(self, x: float, y: float, dx: int, dy: int) -> None:
        raise NotImplementedError

    def type_text(self, text: str) -> None:
        raise NotImplementedError

    def key(self, combo: str) -> None:
        raise NotImplementedError

    def frontmost_app(self) -> str | None:
        raise NotImplementedError

    def open_app(self, name: str) -> None:
        raise NotImplementedError

    def running_apps(self) -> list[str]:
        return []


def _run(cmd: list[str], timeout: float = 15, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=timeout, **kw)


class XBackend(Backend):
    """Linux / X11 via xdotool (CI and Linux desktops)."""

    name = "x11"

    def screen_points(self):
        out = _run(["xdotool", "getdisplaygeometry"], text=True).stdout.split()
        return float(out[0]), float(out[1])

    def capture(self) -> bytes:
        p = _run(["import", "-window", "root", "png:-"], timeout=20)
        if p.returncode != 0 or not p.stdout:
            raise RuntimeError("screenshot failed: " + p.stderr.decode(errors="replace")[:200])
        return p.stdout

    def _xy(self, x, y):
        return [str(int(round(x))), str(int(round(y)))]

    def click(self, x, y, button="left", count=1):
        btn = {"left": "1", "middle": "2", "right": "3"}[button]
        _run(["xdotool", "mousemove", *self._xy(x, y), "click", "--repeat", str(count), "--delay", "80", btn])

    def move(self, x, y):
        _run(["xdotool", "mousemove", *self._xy(x, y)])

    def drag(self, x1, y1, x2, y2):
        _run(["xdotool", "mousemove", *self._xy(x1, y1), "mousedown", "1", "mousemove", *self._xy(x2, y2), "mouseup", "1"])

    def scroll(self, x, y, dx, dy):
        _run(["xdotool", "mousemove", *self._xy(x, y)])
        for _ in range(abs(dy)):
            _run(["xdotool", "click", "5" if dy > 0 else "4"])
        for _ in range(abs(dx)):
            _run(["xdotool", "click", "7" if dx > 0 else "6"])

    def type_text(self, text):
        _run(["xdotool", "type", "--delay", "12", "--", text], timeout=120)

    def key(self, combo):
        mods, key = parse_keys(combo)
        k = X_KEYS.get(key, key)
        _run(["xdotool", "key", "+".join([X_MODS.get(m, m) for m in mods] + [k])])

    def frontmost_app(self):
        """The named window under the pointer (bare X servers have no window manager to ask)."""
        def shell(cmd):
            out = _run(cmd, text=True).stdout
            return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

        loc = shell(["xdotool", "getmouselocation", "--shell"])
        mx, my = int(loc.get("X", -1)), int(loc.get("Y", -1))
        ids = _run(["xdotool", "search", "--onlyvisible", "--name", "."], text=True).stdout.split()
        for wid in reversed(ids):                       # later windows are usually on top
            g = shell(["xdotool", "getwindowgeometry", "--shell", wid])
            try:
                x, y, w, h = int(g["X"]), int(g["Y"]), int(g["WIDTH"]), int(g["HEIGHT"])
            except (KeyError, ValueError):
                continue
            if x <= mx < x + w and y <= my < y + h and w < 10000:
                name = _run(["xdotool", "getwindowname", wid], text=True).stdout.strip()
                if name:
                    return name
        return None

    def open_app(self, name):
        exe = shutil.which(name) or shutil.which(name.lower())
        if not exe:
            raise RuntimeError(f"no app called {name}")
        subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


class MacBackend(Backend):
    """macOS: CoreGraphics events through ctypes; no extra packages."""

    name = "macos"

    def __init__(self):
        import ctypes

        self.ct = ctypes
        fw = "/System/Library/Frameworks/{0}.framework/{0}"
        self.cg = ctypes.CDLL(fw.format("CoreGraphics"))
        self.cf = ctypes.CDLL(fw.format("CoreFoundation"))
        self.appsvc = ctypes.CDLL(fw.format("ApplicationServices"))

        class CGPoint(ctypes.Structure):
            _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

        class CGSize(ctypes.Structure):
            _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

        class CGRect(ctypes.Structure):
            _fields_ = [("origin", CGPoint), ("size", CGSize)]

        self.CGPoint = CGPoint
        cg, c = self.cg, ctypes
        cg.CGMainDisplayID.restype = c.c_uint32
        cg.CGDisplayBounds.argtypes = [c.c_uint32]
        cg.CGDisplayBounds.restype = CGRect
        cg.CGEventCreateMouseEvent.argtypes = [c.c_void_p, c.c_uint32, CGPoint, c.c_uint32]
        cg.CGEventCreateMouseEvent.restype = c.c_void_p
        cg.CGEventCreateKeyboardEvent.argtypes = [c.c_void_p, c.c_uint16, c.c_bool]
        cg.CGEventCreateKeyboardEvent.restype = c.c_void_p
        cg.CGEventKeyboardSetUnicodeString.argtypes = [c.c_void_p, c.c_ulong, c.POINTER(c.c_uint16)]
        cg.CGEventKeyboardSetUnicodeString.restype = None
        cg.CGEventSetFlags.argtypes = [c.c_void_p, c.c_uint64]
        cg.CGEventSetFlags.restype = None
        cg.CGEventSetIntegerValueField.argtypes = [c.c_void_p, c.c_uint32, c.c_int64]
        cg.CGEventSetIntegerValueField.restype = None
        cg.CGEventPost.argtypes = [c.c_uint32, c.c_void_p]
        cg.CGEventPost.restype = None
        cg.CGEventCreateScrollWheelEvent2.argtypes = [c.c_void_p, c.c_uint32, c.c_uint32, c.c_int32, c.c_int32, c.c_int32]
        cg.CGEventCreateScrollWheelEvent2.restype = c.c_void_p
        self.cf.CFRelease.argtypes = [c.c_void_p]
        self.cf.CFRelease.restype = None
        for fn in ("CGPreflightScreenCaptureAccess", "CGRequestScreenCaptureAccess"):
            if hasattr(cg, fn):
                getattr(cg, fn).restype = c.c_bool
        self.appsvc.AXIsProcessTrusted.restype = c.c_bool

    # permissions
    def permissions(self):
        screen = bool(self.cg.CGPreflightScreenCaptureAccess()) if hasattr(self.cg, "CGPreflightScreenCaptureAccess") else None
        return {"screen": screen, "control": bool(self.appsvc.AXIsProcessTrusted())}

    def request_screen(self) -> None:
        if hasattr(self.cg, "CGRequestScreenCaptureAccess"):
            self.cg.CGRequestScreenCaptureAccess()

    # helpers
    def _post(self, ev):
        if ev:
            self.cg.CGEventPost(0, ev)      # kCGHIDEventTap
            self.cf.CFRelease(ev)

    def _mouse(self, kind, x, y, button=0, count=1):
        ev = self.cg.CGEventCreateMouseEvent(None, kind, self.CGPoint(x, y), button)
        if count > 1:
            self.cg.CGEventSetIntegerValueField(ev, 1, count)   # kCGMouseEventClickState
        self._post(ev)

    def screen_points(self):
        r = self.cg.CGDisplayBounds(self.cg.CGMainDisplayID())
        return r.size.width, r.size.height

    def capture(self) -> bytes:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="grid-screen-")
        os.close(fd)
        try:
            p = _run(["/usr/sbin/screencapture", "-x", "-m", "-t", "png", path], timeout=20)
            if p.returncode != 0:
                raise RuntimeError("screenshot failed: " + p.stderr.decode(errors="replace")[:200])
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def click(self, x, y, button="left", count=1):
        down, up, btn = {"left": (1, 2, 0), "right": (3, 4, 1), "middle": (25, 26, 2)}[button]
        self._mouse(5, x, y)          # move there first (some apps need the hover)
        time.sleep(0.05)
        for i in range(1, count + 1):
            self._mouse(down, x, y, btn, i)
            self._mouse(up, x, y, btn, i)
            time.sleep(0.06)

    def move(self, x, y):
        self._mouse(5, x, y)

    def drag(self, x1, y1, x2, y2):
        self._mouse(5, x1, y1)
        self._mouse(1, x1, y1)
        steps = 12
        for i in range(1, steps + 1):
            self._mouse(6, x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
            time.sleep(0.015)
        self._mouse(2, x2, y2)

    def scroll(self, x, y, dx, dy):
        self._mouse(5, x, y)
        ev = self.cg.CGEventCreateScrollWheelEvent2(None, 1, 2, -int(dy), -int(dx), 0)   # lines; down = negative
        self._post(ev)

    def _key_event(self, code: int, down: bool, flags: int = 0):
        ev = self.cg.CGEventCreateKeyboardEvent(None, code, down)
        if flags:
            self.cg.CGEventSetFlags(ev, flags)
        self._post(ev)

    def key(self, combo):
        mods, key = parse_keys(combo)
        flags = 0
        for m in mods:
            flags |= MAC_FLAGS[m]
        code = MAC_KEYCODES[key]
        self._key_event(code, True, flags)
        self._key_event(code, False, flags)

    def type_text(self, text):
        c = self.ct
        for i, line in enumerate(text.split("\n")):
            if i:
                self.key("return")
            units = list(line.encode("utf-16-le"))
            codes = [units[j] | (units[j + 1] << 8) for j in range(0, len(units), 2)]
            for k in range(0, len(codes), 16):
                chunk = codes[k:k + 16]
                arr = (c.c_uint16 * len(chunk))(*chunk)
                for down in (True, False):
                    ev = self.cg.CGEventCreateKeyboardEvent(None, 0, down)
                    self.cg.CGEventKeyboardSetUnicodeString(ev, len(chunk), arr)
                    self._post(ev)
                time.sleep(0.01)

    def frontmost_app(self):
        front = _run(["/usr/bin/lsappinfo", "front"], text=True).stdout.strip()
        if not front:
            return None
        info = _run(["/usr/bin/lsappinfo", "info", "-only", "name", front], text=True).stdout
        m = re.search(r'"(?:LSDisplayName|name)"\s*=\s*"([^"]+)"', info)
        return m.group(1) if m else None

    def open_app(self, name):
        p = _run(["/usr/bin/open", "-a", name], text=True)
        if p.returncode != 0:
            raise RuntimeError(f"couldn't open {name}: {p.stderr.strip()[:200]}")

    def running_apps(self):
        out = _run(["/usr/bin/lsappinfo", "visibleProcessList"], text=True).stdout
        return re.findall(r'"([^"]+)"', out)


_BACKEND: Backend | None = None
_LOCK = threading.Lock()


def backend() -> Backend | None:
    """The backend for this machine, or None when Grid can't control it."""
    global _BACKEND
    with _LOCK:
        if _BACKEND is None:
            try:
                if sys.platform == "darwin":
                    _BACKEND = MacBackend()
                elif os.environ.get("DISPLAY") and shutil.which("xdotool") and shutil.which("import"):
                    _BACKEND = XBackend()
            except Exception:
                _BACKEND = None
        return _BACKEND


def set_backend(b: Backend | None) -> None:
    """Tests swap in a fake."""
    global _BACKEND
    with _LOCK:
        _BACKEND = b


SETTINGS_PANES = {
    "control": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
}


def open_settings_pane(which: str) -> None:
    if sys.platform == "darwin" and which in SETTINGS_PANES:
        subprocess.Popen(["/usr/bin/open", SETTINGS_PANES[which]])


SENSITIVE = re.compile(
    r"\b(send|sending|submit|post|publish|tweet|reply all|buy|purchase|order|checkout|check out|pay|payment|"
    r"transfer|donate|subscribe|delete|remove|erase|trash|uninstall|format|sign out|log ?out|password|passcode|"
    r"confirm|accept terms|unsubscribe)\b",
    re.IGNORECASE,
)
