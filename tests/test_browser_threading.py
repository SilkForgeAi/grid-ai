import sys
import threading
from types import ModuleType

from grid.browser_setup import _prepare_display_probe


def test_mac_browser_probe_never_calls_appkit_from_worker(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    browser = ModuleType("browser_use.browser")
    profile = ModuleType("browser_use.browser.profile")
    calls = []

    def probe():
        calls.append(threading.current_thread())
        return "main-thread-display"

    profile.get_display_size = probe
    browser.profile = profile
    monkeypatch.setitem(sys.modules, "browser_use.browser", browser)
    monkeypatch.setitem(sys.modules, "browser_use.browser.profile", profile)
    _prepare_display_probe()
    wrapped = profile.get_display_size
    _prepare_display_probe()
    assert profile.get_display_size is wrapped
    results = []
    worker = threading.Thread(target=lambda: results.append(profile.get_display_size()))
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert results == [None]
    assert calls == []
    assert profile.get_display_size() == "main-thread-display"
    assert calls == [threading.main_thread()]
