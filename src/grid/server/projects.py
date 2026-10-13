"""Projects (folders Grid works in) and safe file operations inside them.

Every path from the browser is relative to a project root and is resolved and
checked to stay inside it (symlinks included). Deleting moves things to
~/.grid/trash instead of erasing them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from grid.learning import STARTERS, starter_files
from grid.project import grid_home

HIDDEN = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", ".mypy_cache",
          ".ruff_cache", ".DS_Store", ".tox", ".idea", ".next", "dist", "build", ".grid"}
MAX_READ = 2 * 1024 * 1024
_NAME_OK = re.compile(r"^[^/\\\x00]+$")


class ProjectError(ValueError):
    pass


@dataclass
class Project:
    id: str
    name: str
    path: str
    created: float
    last_opened: float | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["exists"] = Path(self.path).is_dir()
        return d


class ProjectRegistry:
    def __init__(self, path: Path | None = None):
        self.path = path or (grid_home() / "projects.json")

    def _read(self) -> dict[str, dict]:
        if not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[Project]:
        items = [Project(**raw) for raw in self._read().values()]
        return sorted(items, key=lambda p: -(p.last_opened or p.created))

    def get(self, pid: str) -> Project:
        raw = self._read().get(pid)
        if raw is None:
            raise ProjectError(f"no project {pid!r}")
        return Project(**raw)

    def by_path(self, path: str) -> Project | None:
        real = os.path.realpath(path)
        return next((p for p in self.list() if os.path.realpath(p.path) == real), None)

    def _save(self, p: Project) -> Project:
        data = self._read()
        data[p.id] = asdict(p)
        self._write(data)
        return p

    def open(self, path: str) -> Project:
        real = os.path.realpath(os.path.expanduser(path))
        if not os.path.isdir(real):
            raise ProjectError(f"folder not found: {path}")
        if real in ("/", os.path.realpath(Path.home())):
            raise ProjectError("pick a project folder, not your whole home directory or /")
        existing = self.by_path(real)
        if existing:
            existing.last_opened = time.time()
            return self._save(existing)
        return self._save(Project(id=uuid.uuid4().hex[:10], name=os.path.basename(real) or real,
                                  path=real, created=time.time(), last_opened=time.time()))

    def create(self, name: str, root: str, *, git_init: bool = True, template: str = "empty") -> Project:
        name = name.strip()
        if not name or not _NAME_OK.match(name) or name in (".", ".."):
            raise ProjectError("project name can't be empty or contain slashes")
        if template not in TEMPLATES:
            raise ProjectError(f"unknown template {template!r}")
        base = Path(os.path.expanduser(root))
        base.mkdir(parents=True, exist_ok=True)
        target = base / name
        if target.exists():
            raise ProjectError(f"{target} already exists - open it instead")
        target.mkdir()
        _apply_template(target, name, template)
        if git_init and shutil.which("git"):
            subprocess.run(["git", "init", "-q"], cwd=target, check=False, capture_output=True)
        return self.open(str(target))

    def forget(self, pid: str) -> None:
        data = self._read()
        data.pop(pid, None)
        self._write(data)

    def touch(self, pid: str) -> None:
        p = self.get(pid)
        p.last_opened = time.time()
        self._save(p)


TEMPLATES = ("empty", "python", *(item["id"] for item in STARTERS))


def _apply_template(target: Path, name: str, template: str) -> None:
    if template not in TEMPLATES:
        raise ProjectError(f"unknown template {template!r}")
    if template in {item["id"] for item in STARTERS}:
        for filename, text in starter_files(template).items():
            (target / filename).write_text(text, encoding="utf-8")
        return
    (target / "README.md").write_text(f"# {name}\n")
    grid_md = f"# Instructions for Grid in {name}\n\n<!-- Add project rules here. -->\n"
    if template == "python":
        pkg = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_") or "app"
        (target / pkg).mkdir()
        (target / pkg / "__init__.py").write_text("")
        (target / "tests").mkdir()
        (target / "tests" / f"test_{pkg}.py").write_text(f"import {pkg}  # noqa: F401\n\n\ndef test_imports():\n    assert True\n")
        (target / "conftest.py").write_text("")
        (target / ".gitignore").write_text("__pycache__/\n.venv/\n.pytest_cache/\n")
        grid_md += "\nverify: python -m pytest -q\n"
    (target / "GRID.md").write_text(grid_md)


# -- files -----------------------------------------------------------------------

class FileOps:
    def __init__(self, root: str):
        self.root = Path(os.path.realpath(root))

    def resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        rel = (rel or "").strip()
        if "\x00" in rel or rel.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", rel):
            raise ProjectError("use a path relative to the project")
        candidate = Path(os.path.realpath(self.root / rel))
        if candidate != self.root and self.root not in candidate.parents:
            raise ProjectError("path is outside the project")
        if must_exist and not candidate.exists():
            raise ProjectError(f"not found: {rel}")
        return candidate

    def rel(self, p: Path) -> str:
        return "" if p == self.root else str(p.relative_to(self.root))

    def tree(self, rel: str = "", show_hidden: bool = False) -> list[dict]:
        d = self.resolve(rel, must_exist=True)
        if not d.is_dir():
            raise ProjectError("not a folder")
        out = []
        for child in d.iterdir():
            if not show_hidden and child.name in HIDDEN:
                continue
            try:
                is_dir = child.is_dir()
                size = child.stat().st_size if not is_dir else None
            except OSError:
                continue
            out.append({"name": child.name, "path": f"{self.rel(d)}/{child.name}".lstrip("/"),
                        "type": "dir" if is_dir else "file", "size": size})
        out.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        return out

    def read(self, rel: str) -> dict:
        p = self.resolve(rel, must_exist=True)
        if p.is_dir():
            raise ProjectError("that's a folder")
        size = p.stat().st_size
        with open(p, "rb") as fh:
            data = fh.read(MAX_READ + 1)
        truncated = len(data) > MAX_READ
        data = data[:MAX_READ]
        if b"\x00" in data[:8192]:
            return {"path": rel, "binary": True, "size": size, "text": None, "truncated": False}
        return {"path": rel, "binary": False, "size": size, "truncated": truncated,
                "version": hashlib.sha256(data).hexdigest() if not truncated else None,
                "text": data.decode("utf-8", errors="replace")}

    def write(self, rel: str, text: str) -> None:
        p = self.resolve(rel)
        if p.is_dir():
            raise ProjectError("that's a folder")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def new_file(self, rel: str) -> None:
        p = self.resolve(rel)
        if p.exists():
            raise ProjectError(f"{rel} already exists")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()

    def mkdir(self, rel: str) -> None:
        p = self.resolve(rel)
        if p.exists():
            raise ProjectError(f"{rel} already exists")
        p.mkdir(parents=True)

    def rename(self, rel: str, to: str) -> None:
        src = self.resolve(rel, must_exist=True)
        dst = self.resolve(to)
        if src == self.root:
            raise ProjectError("can't rename the project root")
        if dst.exists():
            raise ProjectError(f"{to} already exists")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

    def delete(self, rel: str, trash_root: Path | None = None) -> str:
        """Move to Grid's trash; returns where it went."""
        src = self.resolve(rel, must_exist=True)
        if src == self.root:
            raise ProjectError("can't delete the project root")
        trash = (trash_root or (grid_home() / "trash")) / f"{self.root.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        dest = trash / self.rel(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return str(dest)


def browse_dirs(path: str | None) -> dict:
    """Folders under `path` (default: home) for the open-folder dialog."""
    home = Path.home().resolve()
    p = Path(os.path.realpath(os.path.expanduser(path or str(home))))
    if not p.is_dir():
        raise ProjectError(f"not a folder: {path}")
    dirs = []
    try:
        for child in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            dirs.append({"name": child.name, "path": str(child)})
    except PermissionError:
        pass
    return {"path": str(p), "parent": str(p.parent) if p != p.parent else None, "dirs": dirs[:500],
            "home": str(home)}
