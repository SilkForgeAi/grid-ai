"""Folders outside the project that the user let Grid use.

Grid works inside the project by default. To touch anything else on the Mac
(save a PDF to ~/Downloads, read notes in ~/Documents) it asks per folder:
allow once (this chat), always, or deny. "Always" grants live in
~/.grid/access.json; "once" grants live only in memory for one chat.

Some places can never be granted, whatever the user clicks: credential and
key folders, Grid's own data, system folders, and the whole home folder or /.

Inside a granted folder the normal safety rules still apply (recursive
deletes, secrets files and so on still ask first).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from grid.project import grid_home


def _home() -> str:
    return os.path.realpath(os.path.expanduser("~"))

# Never grantable (prefix match after realpath).
_PROTECTED_UNDER_HOME = [
    ".ssh", ".aws", ".gnupg", ".config/gcloud", ".kube", ".docker", ".netrc", ".npmrc", ".pypirc",
    "Library/Keychains", "Library/Cookies", "Library/Application Support/Google/Chrome",
    "Library/Application Support/Firefox", "Library/Safari", "Library/Mail", "Library/Messages",
    ".grid",
]
_PROTECTED_SYSTEM = ["/System", "/bin", "/sbin", "/usr", "/etc", "/private/etc", "/var", "/private/var",
                     "/dev", "/Library", "/Applications", "/opt", "/boot", "/proc", "/sys", "/root"]


def _real(path: str) -> str:
    return os.path.realpath(os.path.expanduser(os.path.expandvars(path)))


def is_under(path: str, root: str) -> bool:
    path, root = _real(path), _real(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def protected_reason(path: str) -> str | None:
    """Why a folder can never be granted, or None if it can be."""
    real = _real(path)
    if real in ("/", _home()) or real == os.path.dirname(_home()):
        return "that's the whole computer or your whole home folder - pick a specific folder"
    for rel in _PROTECTED_UNDER_HOME:
        p = os.path.join(_home(), rel)
        if is_under(real, p) or is_under(p, real):
            return f"{rel} holds keys or private data - Grid never gets access to it"
    gh = str(grid_home())
    if is_under(real, gh) or is_under(gh, real):
        return "that's Grid's own data folder"
    for p in _PROTECTED_SYSTEM:
        if is_under(real, p) and not is_under(real, _home()):
            return "that's a system folder"
    return None


class AccessStore:
    """Persistent "always" grants + per-chat "once" grants."""

    _session: dict[str, set[str]] = {}       # chat id -> folders allowed for that chat
    _lock = threading.Lock()

    def __init__(self, path: Path | None = None):
        self.path = path or (grid_home() / "access.json")

    # -- persistent ------------------------------------------------------------
    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"folders": {}}
        data.setdefault("folders", {})
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def folders(self) -> list[dict]:
        return [{"path": p, **meta} for p, meta in sorted(self._read()["folders"].items())]

    def grant(self, folder: str, *, chat: str | None = None, always: bool = False, reason: str = "") -> str:
        real = _real(folder)
        why = protected_reason(real)
        if why:
            raise PermissionError(why)
        if not os.path.isdir(real):
            raise FileNotFoundError(f"{folder} isn't a folder")
        if always:
            with self._lock:
                data = self._read()
                data["folders"][real] = {"granted": time.time(), "reason": reason[:200]}
                self._write(data)
        elif chat:
            with self._lock:
                self._session.setdefault(chat, set()).add(real)
        return real

    def revoke(self, folder: str) -> None:
        real = _real(folder)
        with self._lock:
            data = self._read()
            data["folders"].pop(real, None)
            data["folders"].pop(folder, None)
            self._write(data)
            for s in self._session.values():
                s.discard(real)

    def roots(self, chat: str | None = None) -> list[str]:
        out = list(self._read()["folders"])
        if chat:
            with self._lock:
                out += sorted(self._session.get(chat, set()))
        return [r for r in out if protected_reason(r) is None]

    def allowed(self, path: str, chat: str | None = None) -> bool:
        return _not_secret_area(path) and any(is_under(path, r) for r in self.roots(chat))


def _not_secret_area(path: str) -> bool:
    real = _real(path)
    return not any(is_under(real, os.path.join(_home(), rel)) for rel in _PROTECTED_UNDER_HOME)


def folder_for(path: str) -> str:
    """The folder to ask about for a path: the path itself if it's a folder,
    else its parent (creating nothing)."""
    real = _real(path)
    if os.path.isdir(real):
        return real
    parent = os.path.dirname(real)
    while parent and not os.path.isdir(parent) and parent != os.path.dirname(parent):
        parent = os.path.dirname(parent)
    return parent or real


def pretty(path: str) -> str:
    real = _real(path)
    return "~" + real[len(_home()):] if is_under(real, _home()) else real


def granted_roots(chat: str | None = None) -> list[str]:
    """Folders the safety rules treat like the project (always + this chat's once grants)."""
    try:
        return AccessStore().roots(chat)
    except Exception:
        return []


class AppStore:
    """Apps the user let Grid control (and whether Grid may see the screen at all).
    "always" grants live in ~/.grid/apps.json; "once" grants last for one chat."""

    _session: dict[str, set[str]] = {}
    _lock = threading.Lock()
    SCREEN = "(your screen)"

    def __init__(self, path: Path | None = None):
        self.path = path or (grid_home() / "apps.json")

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"apps": {}}
        data.setdefault("apps", {})
        return data

    def apps(self) -> list[dict]:
        return [{"name": meta.get("name", k), "key": k, **meta} for k, meta in sorted(self._read()["apps"].items())]

    def allowed(self, app: str, chat: str | None = None) -> bool:
        key = app.strip().lower()
        if key in self._read()["apps"]:
            return True
        with self._lock:
            return bool(chat) and key in self._session.get(chat, set())

    def grant(self, app: str, *, chat: str | None = None, always: bool = False) -> None:
        key = app.strip().lower()
        if not key:
            raise ValueError("no app name")
        if always:
            with self._lock:
                data = self._read()
                data["apps"][key] = {"name": app.strip(), "granted": time.time()}
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
                os.replace(tmp, self.path)
        elif chat:
            with self._lock:
                self._session.setdefault(chat, set()).add(key)

    def revoke(self, app: str) -> None:
        key = app.strip().lower()
        with self._lock:
            data = self._read()
            data["apps"].pop(key, None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
            for s in self._session.values():
                s.discard(key)
