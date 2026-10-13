"""Checkpoints and undo, via a shadow git repository.

Every change the agent makes becomes a checkpoint: a commit in a private git
repo under ~/.grid/checkpoints/<project-key>.git whose work tree is the user's
project. The user's own repo, branches, index and history are never touched,
and it works in folders that aren't git repos at all. Respects the project's
.gitignore plus a default exclude list (node_modules, virtualenvs, caches).

    store = CheckpointStore(workspace)
    cp = store.snapshot("after edit buggy.py")   # None if nothing changed
    store.restore(cp.sha)                        # undo back to it (undoable)
    print(store.diff(start.sha, store.head()))

Pure Python + the git CLI. No SDK import.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from grid.project import grid_home, project_key

DEFAULT_EXCLUDES = """\
.git/
.grid/
node_modules/
.venv/
venv/
env/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
.tox/
*.egg-info/
dist/
build/
target/
.next/
.DS_Store
"""

_EMPTY = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's empty tree


class CheckpointError(RuntimeError):
    pass


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


@contextlib.contextmanager
def _locked(git_dir: Path):
    """One writer at a time per project: the agent, the editor's save and a
    replace-all can all checkpoint at once (threads), and so can a scheduled
    run in another process (file lock)."""
    key = str(git_dir)
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.RLock())
    with lock:
        if getattr(_held, key, 0):
            yield          # re-entrant within this thread (restore -> current -> snapshot)
            return
        git_dir.parent.mkdir(parents=True, exist_ok=True)
        with open(str(git_dir) + ".lock", "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            setattr(_held, key, 1)
            try:
                yield
            finally:
                setattr(_held, key, 0)
                fcntl.flock(fh, fcntl.LOCK_UN)


_held = threading.local()


@dataclass
class Checkpoint:
    id: int
    sha: str
    label: str
    timestamp: float
    session: str | None = None
    tests: str | None = None     # e.g. "5/5 passed" once a test run is tied to it
    good: bool | None = None     # True when tests at this checkpoint didn't regress


class CheckpointStore:
    def __init__(self, workspace: str | os.PathLike, root: Path | None = None,
                 session: str | None = None):
        self.workspace = os.path.realpath(os.fspath(workspace))
        home = Path(os.path.expanduser(os.path.expandvars(os.fspath(Path.home()))))
        if self.workspace in ("/", os.path.realpath(home)):
            raise CheckpointError(
                f"Refusing to checkpoint {self.workspace}: run Grid inside a project folder."
            )
        base = root or (grid_home() / "checkpoints")
        self.git_dir = Path(base) / f"{project_key(self.workspace)}.git"
        self.log_path = Path(base) / f"{project_key(self.workspace)}.jsonl"
        self.session = session
        self._ensure()

    # -- plumbing ----------------------------------------------------------
    def _git(self, *args: str, check: bool = True, input: str | None = None) -> str:
        env = {
            **os.environ,
            "GIT_DIR": str(self.git_dir),
            "GIT_WORK_TREE": self.workspace,
            "GIT_AUTHOR_NAME": "Grid", "GIT_AUTHOR_EMAIL": "grid@local",
            "GIT_COMMITTER_NAME": "Grid", "GIT_COMMITTER_EMAIL": "grid@local",
        }
        env.pop("GIT_INDEX_FILE", None)
        proc = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
             "-c", "core.quotepath=false", *args],
            cwd=self.workspace, env=env, capture_output=True, text=True, input=input,
            timeout=120,
        )
        if check and proc.returncode != 0:
            raise CheckpointError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout

    def _ensure(self) -> None:
        if (self.git_dir / "HEAD").exists():
            return
        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        self._git("init", "-q")
        self._git("config", "core.bare", "false")
        self._git("config", "core.worktree", self.workspace)
        self._git("config", "gc.auto", "0")
        info = self.git_dir / "info"
        info.mkdir(exist_ok=True)
        (info / "exclude").write_text(DEFAULT_EXCLUDES, encoding="utf-8")

    def head(self) -> str | None:
        out = self._git("rev-parse", "--verify", "-q", "HEAD", check=False).strip()
        return out or None

    def _tree_of(self, sha: str | None) -> str:
        if not sha:
            return _EMPTY
        return self._git("rev-parse", f"{sha}^{{tree}}").strip()

    # -- records -----------------------------------------------------------
    def list(self) -> list[Checkpoint]:
        if not self.log_path.exists():
            return []
        out: dict[int, Checkpoint] = {}
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                cp = Checkpoint(**json.loads(line))
            except (json.JSONDecodeError, TypeError):
                continue
            out[cp.id] = cp  # later lines update earlier ones (e.g. test status)
        return [out[k] for k in sorted(out)]

    def _append(self, cp: Checkpoint) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(cp)) + "\n")

    def get(self, ref: str | int) -> Checkpoint | None:
        """Look up by checkpoint number, or by a sha prefix of 7+ characters.
        Numbers win: "1" is checkpoint #1, never a sha that happens to start with 1."""
        cps = self.list()
        ref = str(ref).lstrip("#")
        for cp in cps:
            if str(cp.id) == ref:
                return cp
        if len(ref) >= 7:
            for cp in cps:
                if cp.sha.startswith(ref):
                    return cp
        return None

    def mark(self, cp: Checkpoint, *, tests: str | None = None, good: bool | None = None) -> None:
        if tests is not None:
            cp.tests = tests
        if good is not None:
            cp.good = good
        self._append(cp)

    def last_good(self) -> Checkpoint | None:
        good = [cp for cp in self.list() if cp.good]
        return good[-1] if good else None

    # -- operations --------------------------------------------------------
    def snapshot(self, label: str, *, force: bool = False) -> Checkpoint | None:
        """Commit the current work tree. Returns None when nothing changed
        since the last checkpoint (unless force)."""
        with _locked(self.git_dir):
            return self._snapshot(label, force=force)

    def _snapshot(self, label: str, *, force: bool = False) -> Checkpoint | None:
        # Rebuild the index from scratch. Git's stat cache can miss an edit
        # that keeps a file's size and lands in the same timestamp tick as the
        # last snapshot ("a - b" -> "a + b"), and a missed edit is a missed
        # checkpoint. Hashing the tree is cheap next to an agent step.
        (self.git_dir / "index").unlink(missing_ok=True)
        self._git("add", "-A", ".")
        tree = self._git("write-tree").strip()
        parent = self.head()
        if not force and parent and tree == self._tree_of(parent):
            return None
        args = ["commit-tree", tree, "-m", label]
        if parent:
            args += ["-p", parent]
        sha = self._git(*args).strip()
        self._git("update-ref", "HEAD", sha)
        existing = self.list()
        cp = Checkpoint(id=(existing[-1].id + 1 if existing else 0), sha=sha, label=label,
                        timestamp=time.time(), session=self.session)
        self._git("update-ref", f"refs/grid/cp-{cp.id}", sha)  # keep reachable after undo
        self._append(cp)
        return cp

    def current(self, label: str = "current") -> Checkpoint:
        """A checkpoint for the work tree right now (reuses HEAD if unchanged)."""
        cp = self.snapshot(label)
        if cp is not None:
            return cp
        head = self.head()
        found = [c for c in self.list() if c.sha == head]
        if found:
            return found[-1]
        return self.snapshot(label, force=True)  # type: ignore[return-value]

    def restore(self, ref: str | int) -> tuple[Checkpoint, Checkpoint]:
        """Make the work tree match checkpoint `ref`. The state being replaced
        is checkpointed first, so an undo can itself be undone.

        Returns (target, saved_before_restore)."""
        target = self.get(ref)
        if target is None:
            raise CheckpointError(f"No checkpoint {ref!r}")
        with _locked(self.git_dir):
            before = self.current(f"before restore to #{target.id}")
            # Files the agent created after the target are tracked in `before`, so
            # reset --hard removes them; files ignored or never seen are untouched.
            self._git("reset", "-q", "--hard", target.sha)
        return target, before

    def changed_files(self, a: str, b: str | None = None) -> list[str]:
        b = b or self.current().sha
        out = self._git("diff", "--name-status", a, b)
        return [line for line in out.splitlines() if line.strip()]

    def diff(self, a: str, b: str | None = None, *, stat: bool = False) -> str:
        b = b or self.current().sha
        args = ["diff", "--stat"] if stat else ["diff"]
        return self._git(*args, a, b)

    # -- single files --------------------------------------------------------
    def _rel(self, path: str) -> str:
        p = os.path.realpath(os.path.join(self.workspace, path))
        if p != self.workspace and not p.startswith(self.workspace + os.sep):
            raise CheckpointError("path is outside the project")
        return os.path.relpath(p, self.workspace).replace(os.sep, "/")

    def read_at(self, ref: str | int, path: str) -> str | None:
        """File content at a checkpoint, or None if it didn't exist then."""
        cp = self.get(ref)
        if cp is None:
            raise CheckpointError(f"No checkpoint {ref!r}")
        rel = self._rel(path)
        out = subprocess.run(
            ["git", "show", f"{cp.sha}:{rel}"], cwd=self.workspace, capture_output=True,
            env={**os.environ, "GIT_DIR": str(self.git_dir), "GIT_WORK_TREE": self.workspace}, timeout=60,
        )
        if out.returncode != 0:
            return None
        return out.stdout.decode("utf-8", errors="replace")

    def restore_file(self, ref: str | int, path: str) -> str:
        """Put one file back to how it was at checkpoint `ref` (deleting it if
        it didn't exist then). The current state is checkpointed first.
        Returns "restored" or "removed"."""
        cp = self.get(ref)
        if cp is None:
            raise CheckpointError(f"No checkpoint {ref!r}")
        rel = self._rel(path)
        with _locked(self.git_dir):
            return self._restore_file(cp, rel)

    def _restore_file(self, cp: Checkpoint, rel: str) -> str:
        self.current(f"before reverting {rel}")
        content = subprocess.run(
            ["git", "show", f"{cp.sha}:{rel}"], cwd=self.workspace, capture_output=True,
            env={**os.environ, "GIT_DIR": str(self.git_dir), "GIT_WORK_TREE": self.workspace}, timeout=60,
        )
        target = Path(self.workspace) / rel
        if content.returncode != 0:
            if target.exists():
                target.unlink()
            result = "removed"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content.stdout)
            result = "restored"
        self.snapshot(f"reverted {rel} to #{cp.id}")
        return result
