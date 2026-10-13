"""Consistency: before Grid accepts "done", the work is looked over twice.

1. Grid's own quick checks on every file the task changed - no model, and nothing from the
   project runs: Python, JSON and TOML must still parse, and no merge-conflict markers may be
   left behind. A problem here blocks "done" the same way a failing test does.
2. One review round: the agent re-opens what it changed and checks that the pieces agree with
   each other (names and signatures at every call site, docs and comments, nothing half-done),
   fixes what it finds, and finishes again. The tests run after the review, so they also
   cover anything the review changed.
"""

from __future__ import annotations

import ast
import json
import os
import tomllib

MAX_BYTES = 2_000_000
_SKIP_DIRS = ("node_modules/", ".git/", ".venv/", "venv/", "__pycache__/", "dist/", "build/")
_MARKERS = ("<<<<<<< ", ">>>>>>> ")


def changed_paths(changed: list[str]) -> list[str]:
    """Paths from `git diff --name-status` lines that still exist after the task (no deletions)."""
    out = []
    for line in changed:
        parts = line.split("\t")
        if len(parts) < 2 or parts[0].startswith("D"):
            continue
        path = parts[-1].strip()
        if path and not any(f"/{d}" in f"/{path}" for d in _SKIP_DIRS) and path not in out:
            out.append(path)
    return out


def _problem(path: str, source: str) -> str | None:
    lines = source.splitlines()
    if any(ln.startswith(_MARKERS[0]) for ln in lines) and any(ln.startswith(_MARKERS[1]) for ln in lines):
        n = next(i for i, ln in enumerate(lines, 1) if ln.startswith(_MARKERS[0]))
        return f"{path} line {n}: merge-conflict markers (<<<<<<< / >>>>>>>) were left in the file"
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".py":
            ast.parse(source, filename=path)
        elif ext in (".json", ".ipynb") and source.strip():
            json.loads(source)
        elif ext == ".toml":
            tomllib.loads(source)
    except SyntaxError as exc:
        return f"{path} line {exc.lineno}: Python syntax error ({exc.msg})"
    except json.JSONDecodeError as exc:
        return f"{path} line {exc.lineno}: not valid JSON ({exc.msg})"
    except tomllib.TOMLDecodeError as exc:
        return f"{path}: not valid TOML ({exc})"
    except (ValueError, RecursionError) as exc:
        return f"{path}: could not be read ({type(exc).__name__})"
    return None


def static_problems(workspace: str, changed: list[str], limit: int = 12) -> list[str]:
    """Problems Grid can see without running anything, in the files a task changed."""
    root = os.path.realpath(workspace)
    found = []
    for rel in changed_paths(changed):
        path = os.path.realpath(os.path.join(root, rel))
        if not path.startswith(root + os.sep) or not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > MAX_BYTES:
                continue
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
        except (OSError, UnicodeDecodeError):
            continue       # binary or unreadable: nothing to check
        problem = _problem(rel, source)
        if problem:
            found.append(problem)
            if len(found) >= limit:
                break
    return found


def review_request(files: list[str], problems: list[str] | None = None) -> str:
    """The message that sends the agent back for its one review round."""
    shown = files[:25]
    more = f"\n- ...and {len(files) - len(shown)} more" if len(files) > len(shown) else ""
    found = ""
    if problems:
        found = "\n\nGrid already found these, fix them first:\n" + "\n".join(f"- {p}" for p in problems)
    return (
        "Before Grid accepts this as done, review your own changes for consistency. You changed:\n"
        + "\n".join(f"- {f}" for f in shown) + more + found + "\n\n"
        "Re-open each changed file, and the places that use what you changed, and check:\n"
        "1. Names, signatures, types and return values agree everywhere they are used: callers, imports and exports updated.\n"
        "2. Comments, docstrings, README/docs and help text still describe what the code now does.\n"
        "3. Nothing is half-done: no TODO/FIXME you added, debug prints, commented-out code, or unused imports and variables.\n"
        "4. The same situation is handled the same way across the files (errors, empty input, edge cases).\n"
        "5. A test exercises the change; add one if not.\n"
        "Fix what you find. Then finish again with your answer for the user (briefly, what you did), keep any "
        "VERIFY: line, and end with one line `REVIEW: <what you checked and what you fixed, or no issues found>`."
    )
