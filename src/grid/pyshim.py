"""A `python` command for Macs that only have `python3`.

macOS ships `python3` but no `python`, while projects, READMEs and models all say
`python main.py` or `python -m pytest`. Without this, a project's own check fails with
"command not found" (exit 127) and can never pass, and the agent wastes steps on it.

When `python` is missing and `python3` exists, Grid puts a `python` that runs `python3`
in its own bin folder and adds that folder to the PATH of the processes it starts (checks,
the agent's terminal, the app's terminal). The user's system is not changed.
"""

from __future__ import annotations

import os
import shutil

from grid.project import grid_home


def ensure_python_command(environ: dict | None = None) -> str | None:
    """Make `python` resolve to python3 for Grid's processes. Returns the folder added to
    PATH, or None when nothing was needed (or possible)."""
    env = os.environ if environ is None else environ
    path = env.get("PATH", "")
    shim_dir = grid_home() / "bin"
    found = shutil.which("python", path=path)
    if found:      # a real python, or ours from an earlier call
        return str(shim_dir) if os.path.dirname(found) == str(shim_dir) else None
    python3 = shutil.which("python3", path=path)
    if not python3:
        return None
    shim = shim_dir / "python"
    try:
        shim_dir.mkdir(parents=True, exist_ok=True)
        if shim.is_symlink() or shim.exists():
            if os.path.realpath(shim) == os.path.realpath(python3):
                pass
            else:
                shim.unlink()
                os.symlink(python3, shim)
        else:
            os.symlink(python3, shim)
    except OSError:
        return None
    folder = str(shim_dir)
    if folder not in path.split(os.pathsep):
        env["PATH"] = folder + (os.pathsep + path if path else "")
    return folder
