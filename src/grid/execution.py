"""A project has one writer: chat, a schedule, or an editor transaction."""
from __future__ import annotations

import contextlib
import fcntl
import functools

from grid.project import grid_home, project_key


@contextlib.contextmanager
def project_execution(workspace):
    folder = grid_home() / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{project_key(workspace)}.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This project is busy. Stop its task or wait before changing files.") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def exclusive_task(fn):
    @functools.wraps(fn)
    def wrapped(self, *args, **kwargs):
        with project_execution(self.workspace):
            return fn(self, *args, **kwargs)
    return wrapped
