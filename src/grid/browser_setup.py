"""Grid's own browser: a separate Chrome/Chromium profile the agent drives
(not signed in to the user's accounts). Uses Google Chrome, Chromium or Edge
if installed; otherwise it can download Playwright's Chromium."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading


def _prepare_display_probe() -> None:
    """Avoid AppKit's process abort when the dependency probes from a worker."""
    if sys.platform != "darwin":
        return
    from browser_use.browser import profile

    original = profile.get_display_size
    if getattr(original, "_grid_thread_safe", False):
        return

    def safe_display_size():
        if threading.current_thread() is not threading.main_thread():
            return None  # browser-use supplies default viewport geometry
        return original()

    safe_display_size._grid_thread_safe = True
    profile.get_display_size = safe_display_size


def chromium_path() -> str | None:
    try:
        _prepare_display_probe()
        from openhands.tools.browser_use.impl import BrowserToolExecutor

        check = BrowserToolExecutor.check_chromium_available
        if hasattr(check, "cache_clear"):        # the SDK caches the answer; Chrome may have been installed since
            check.cache_clear()
        return check()
    except Exception:
        return None


def _uv() -> str | None:
    for cand in (os.environ.get("GRID_UV"), shutil.which("uv"), os.path.expanduser("~/.local/bin/uv"),
                 "/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def install_command() -> list[str] | None:
    uv = _uv()
    if uv:
        return [uv, "tool", "run", "--from", "playwright", "playwright", "install", "chromium"]
    try:
        import playwright  # noqa: F401

        return [sys.executable, "-m", "playwright", "install", "chromium"]
    except ImportError:
        return None


def install() -> dict:
    """Download Playwright's Chromium (~150 MB). Returns {"ok", "path"|"error", "log"}."""
    cmd = install_command()
    if cmd is None:
        return {"ok": False, "error": "Install Google Chrome (google.com/chrome) and Grid will use it."}
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"couldn't download the browser: {exc}"}
    log = (p.stdout + p.stderr)[-3000:]
    path = chromium_path()
    if p.returncode != 0 or not path:
        return {"ok": False, "error": "the browser download failed - check the internet connection", "log": log}
    return {"ok": True, "path": path, "log": log}


BROWSER_PROMPT = """\
- browser_*: Grid's own browser (a separate profile, not signed in to the user's accounts) for sites that need
  clicking, forms or JavaScript. Prefer web_search/web_fetch for just reading. Never type passwords, card numbers
  or other secrets; if a site needs a login, stop and ask the user. Screenshots of each step show up in the app."""


_PATCHED = False


def patch_browser() -> None:
    """openhands-tools 1.54 expects browser-use's state call to return JSON text, but the
    browser-use it installs returns (json, screenshot). Accept both."""
    global _PATCHED
    if _PATCHED:
        return
    try:
        import json

        _prepare_display_probe()
        from openhands.tools.browser_use.definition import BrowserObservation
        from openhands.tools.browser_use.impl import BrowserToolExecutor
    except Exception:
        return

    async def get_state(self, include_screenshot: bool = False):
        await self._ensure_initialized()
        result = await self._server._get_browser_state(include_screenshot)
        shot = None
        if isinstance(result, tuple):
            result, shot = result[0], (result[1] if len(result) > 1 else None)
        text = result if isinstance(result, str) else json.dumps(result)
        if include_screenshot and shot is None:
            try:
                data = json.loads(text)
                shot = data.pop("screenshot", None)
                text = json.dumps(data, indent=2)
            except (json.JSONDecodeError, AttributeError):
                pass
        return BrowserObservation.from_text(text=text, is_error=text.startswith("Error:"),
                                            screenshot_data=shot if include_screenshot else None,
                                            full_output_save_dir=self.full_output_save_dir)

    BrowserToolExecutor.get_state = get_state
    _PATCHED = True
