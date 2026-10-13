import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('browser_cache', Path(__file__).resolve().parents[1] / 'scripts/browser_cache.py')
cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache)


@pytest.mark.parametrize('platform,suffix', [
    ('linux', '.cache/ms-playwright'), ('darwin', 'Library/Caches/ms-playwright'),
    ('win32', 'AppData/Local/ms-playwright'),
])
def test_browser_cache_survives_disposable_home(tmp_path, platform, suffix):
    env = {'HOME': str(tmp_path / 'real-home')}
    expected = str(tmp_path / 'real-home' / suffix)
    assert cache.preserve_browser_cache(env, platform) == expected
    env['HOME'] = str(tmp_path / 'disposable-home')
    assert cache.preserve_browser_cache(env, platform) == expected


@pytest.mark.parametrize('override', ['0', '/test/shared-browser-cache'])
def test_browser_cache_keeps_explicit_override(override):
    env = {'PLAYWRIGHT_BROWSERS_PATH': override}
    assert cache.preserve_browser_cache(env, 'linux') == override


def test_browser_cache_respects_linux_cache_directory(tmp_path):
    env = {'HOME': str(tmp_path / 'home'), 'XDG_CACHE_HOME': str(tmp_path / 'xdg')}
    assert cache.preserve_browser_cache(env, 'linux') == str(tmp_path / 'xdg/ms-playwright')
