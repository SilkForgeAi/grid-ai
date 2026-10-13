"""Per-project identity, Grid's home directory, instructions, and verify command.

- `project_key` gives every workspace its own memory/checkpoint/session store,
  keyed by absolute path (two folders both named `api` never share a store).
- `load_instructions` reads layered GRID.md instructions (global, repo, folder).
- `detect_verify_command` finds the check Grid runs before accepting "done".

Pure Python, no SDK import.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


def grid_home() -> Path:
    """Root for all Grid state. Override with GRID_HOME (tests use this)."""
    env = os.getenv("GRID_HOME")
    return Path(env).expanduser() if env else Path.home() / ".grid"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "default"


def project_key(workspace: str | os.PathLike) -> str:
    """`<basename-slug>-<8 hex of sha256(abspath)>` — readable and unique."""
    path = os.path.realpath(os.path.abspath(os.fspath(workspace)))
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:8]
    return f"{slug(os.path.basename(path))}-{digest}"


def git_root(workspace: str | os.PathLike) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=os.fspath(workspace), capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return Path(out.stdout.strip())


INSTRUCTION_FILES = ("GRID.md", ".grid/GRID.md")


def load_instructions(workspace: str | os.PathLike) -> str:
    """Layered instructions, most general first so the most specific wins:
    ~/.grid/GRID.md (global) -> <git root>/GRID.md -> <workspace>/GRID.md.

    AGENTS.md / .cursorrules are loaded separately through the
    SDK's project skills, so repos written for other agents work as-is.
    """
    ws = Path(os.path.realpath(os.fspath(workspace)))
    candidates: list[tuple[str, Path]] = [("global", grid_home() / "GRID.md")]
    root = git_root(ws)
    if root is not None and root.resolve() != ws:
        candidates += [("repo", root / f) for f in INSTRUCTION_FILES]
    candidates += [("project", ws / f) for f in INSTRUCTION_FILES]

    seen: set[Path] = set()
    parts: list[str] = []
    for scope, path in candidates:
        try:
            real = path.resolve()
        except OSError:
            continue
        if real in seen or not path.is_file():
            continue
        seen.add(real)
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            parts.append(f"## {scope} instructions ({path.name})\n{text}")
    if not parts:
        return ""
    return "PROJECT INSTRUCTIONS (follow these; later sections override earlier):\n\n" + "\n\n".join(parts)


_VERIFY_LINE = re.compile(r"^\s*verify\s*:\s*`?([^`\n]+?)`?\s*$", re.IGNORECASE | re.MULTILINE)


def verify_from_instructions(workspace: str | os.PathLike) -> tuple[str, str] | None:
    """(command, file) from a `verify: <cmd>` line in the project's GRID.md."""
    ws = Path(os.fspath(workspace))
    for name in INSTRUCTION_FILES:
        f = ws / name
        if f.is_file():
            m = _VERIFY_LINE.search(f.read_text(encoding="utf-8", errors="replace"))
            if m:
                return m.group(1).strip(), name
    return None


def detect_test_runner(workspace: str | os.PathLike) -> str | None:
    """The project's obvious test command, or None."""
    ws = Path(os.fspath(workspace))
    pkg = ws / "package.json"
    if pkg.is_file():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
        except (json.JSONDecodeError, OSError):
            scripts = {}
        test = scripts.get("test", "")
        if test and "no test specified" not in test:
            return "npm test --silent"
    if (ws / "Cargo.toml").is_file():
        return "cargo test"
    if (ws / "go.mod").is_file():
        return "go test ./..."
    if _has_python_tests(ws):
        return f"{_python_for(ws)} -m pytest -q"
    return None


def _python_for(ws: Path) -> str:
    """The project's own virtualenv python when it has one, else python/python3."""
    import shutil

    for venv in (".venv", "venv"):
        cand = ws / venv / "bin" / "python"
        if cand.is_file():
            return f"{venv}/bin/python"
    return "python" if shutil.which("python") else "python3"


def detect_verify_command(workspace: str | os.PathLike) -> str | None:
    """The command Grid runs to prove a task is done.

    Order: a `verify: <cmd>` line in GRID.md, then the project's obvious test
    runner. Returns None when nothing checkable is found."""
    found = verify_from_instructions(workspace)
    return found[0] if found else detect_test_runner(workspace)


def _has_python_tests(ws: Path) -> bool:
    if (ws / "pytest.ini").is_file() or (ws / "conftest.py").is_file():
        return True
    pyproject = ws / "pyproject.toml"
    if pyproject.is_file() and "[tool.pytest" in pyproject.read_text(encoding="utf-8", errors="replace"):
        return True
    skip = {".git", ".venv", "venv", "node_modules", "__pycache__", ".grid", "build", "dist"}
    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in skip and not d.startswith(".")]
        if any(f.startswith("test_") and f.endswith(".py") or f.endswith("_test.py") for f in files):
            return True
        if Path(root).relative_to(ws).parts.__len__() >= 3:
            dirs[:] = []
    return False
