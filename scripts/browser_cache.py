"""Keep browser binaries available while smoke tests use a disposable home."""
from pathlib import Path


def preserve_browser_cache(env, platform):
    if env.get('PLAYWRIGHT_BROWSERS_PATH'):
        return env['PLAYWRIGHT_BROWSERS_PATH']
    home = Path(env.get('HOME') or Path.home())
    if platform == 'darwin':
        cache = home / 'Library/Caches/ms-playwright'
    elif platform == 'win32':
        cache = Path(env.get('LOCALAPPDATA') or home / 'AppData/Local') / 'ms-playwright'
    else:
        cache = Path(env.get('XDG_CACHE_HOME') or home / '.cache') / 'ms-playwright'
    env['PLAYWRIGHT_BROWSERS_PATH'] = str(cache.resolve())
    return env['PLAYWRIGHT_BROWSERS_PATH']
