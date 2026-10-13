"""Cross-session episodic memory.

The SDK's critic/condenser are in-session only. Grid AI's differentiation is that
it *remembers across runs*: when something breaks and gets fixed, it records a
lesson (the "why did this break" note + the fix), and on the next run it recalls
the relevant ones and injects them into the agent's context. Over time the agent
stops repeating the same mistakes in a given project.

This is deliberately simple and dependency-free: newline-delimited JSON on disk,
keyword-scored retrieval. It's the seam a vector store slots into later (Phase 2)
without changing callers. No SDK import — fully unit-tested.

Storage layout (per project):
    <root>/<project-slug>.jsonl      # one Episode per line
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from grid.project import grid_home, project_key
from grid.project import slug as _slug


def default_memory_root() -> Path:
    """Where memory lives by default: ~/.grid/memory (or $GRID_HOME/memory)."""
    return grid_home() / "memory"


_WORD_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it",
    "of", "on", "or", "that", "the", "this", "to", "was", "with", "test", "tests",
    "passing", "passed", "failed", "make", "fix", "add", "change", "please",
}


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and not w.isdigit()}


@dataclass
class Episode:
    """One remembered lesson."""

    error_signature: str          # short, matchable description of what went wrong
    lesson: str                   # the "why this broke" note + how it was fixed
    kind: str = "failure"         # failure | regression | note
    timestamp: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)

    def score(self, query: str) -> int:
        """Keyword-overlap score against a query (higher = more relevant).
        Signature and tags count double; the lesson text counts once, so an
        episode is findable by what was learned, not only by its title."""
        q = _keywords(query)
        head = _keywords(self.error_signature + " " + " ".join(self.tags))
        body = _keywords(self.lesson)
        return 2 * len(q & head) + len(q & (body - head))


@dataclass
class MemoryStore:
    project: str
    root: Path = field(default_factory=default_memory_root)

    @classmethod
    def for_workspace(cls, workspace: str | os.PathLike, root: Path | None = None) -> MemoryStore:
        """Store keyed by the workspace's absolute path, so two folders that
        share a name (`api`, `src`) never share lessons."""
        key = project_key(workspace)
        return cls(project=key, root=root or default_memory_root())

    @property
    def path(self) -> Path:
        return Path(self.root) / f"{_slug(self.project)}.jsonl"

    def add(self, episode: Episode) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(episode)) + "\n")

    def all(self) -> list[Episode]:
        if not self.path.exists():
            return []
        out: list[Episode] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(Episode(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue  # skip corrupt lines rather than crash
        return out

    def recent(self, n: int = 5) -> list[Episode]:
        return sorted(self.all(), key=lambda e: e.timestamp, reverse=True)[:n]

    def search(self, query: str, limit: int = 5) -> list[Episode]:
        """Return the most relevant episodes for a query, best first. Episodes
        with zero keyword overlap are excluded; ties break toward recent."""
        scored = [(e.score(query), e.timestamp, e) for e in self.all()]
        scored = [t for t in scored if t[0] > 0]
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [e for _, _, e in scored[:limit]]

    def recall_prompt(self, query: str, limit: int = 5) -> str:
        """Build a system-prompt fragment from relevant past lessons, or "" if
        there are none. Injected at conversation start (see app.py)."""
        episodes = self.search(query, limit=limit)
        if not episodes:
            return ""
        lines = [
            "LESSONS FROM PAST SESSIONS IN THIS PROJECT "
            "(avoid repeating these mistakes):"
        ]
        for e in episodes:
            lines.append(f"- ({e.kind}) {e.error_signature}: {e.lesson}")
        return "\n".join(lines)

    def delete(self, index: int) -> Episode:
        """Remove the episode at `index` (position in `all()`)."""
        episodes = self.all()
        if not 0 <= index < len(episodes):
            raise IndexError(f"no memory #{index}")
        removed = episodes.pop(index)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(asdict(e)) + "\n" for e in episodes), encoding="utf-8")
        os.replace(tmp, self.path)
        return removed
