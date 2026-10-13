"""Long-term memory that follows the user across chats and projects.

Three kinds, all plain JSON under ~/.grid/memory (the user can see, edit and
delete everything from the app's Memory page):

  - facts about the user (name, goals, experience, preferences, what they've
    learned) - shared by every project;
  - notes for one project (decisions, conventions, where things live);
  - an archive of past chats: every turn's request, Grid's answer, outcome and
    changed files, so Grid can pick up "where we left off" or find "that bug
    from last week" in a later chat.

New chats start with the user facts, the project notes and the last few chats
in their system prompt; the `memory` tool searches everything on demand.
Nothing that looks like a secret is ever stored.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from grid.memory import _keywords
from grid.project import grid_home, project_key

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}|sk_[A-Za-z0-9]{12,}|xai-[A-Za-z0-9]{12,}|gsk_[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_-]{20,}"
    r"|ghp_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:password|passwd|api[_ ]?key|secret|token)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
_LOCK = threading.RLock()
MAX_FACT = 500
MAX_TURN_USER = 1500
MAX_TURN_REPLY = 2500
MAX_CHATS_PER_PROJECT = 300


class MemoryError_(ValueError):
    pass


def looks_secret(text: str) -> bool:
    return bool(_SECRET_RE.search(text or ""))


def scrub(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text or "")


def _root() -> Path:
    return grid_home() / "memory"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# -- facts ------------------------------------------------------------------------

@dataclass
class Fact:
    id: str
    text: str
    scope: str                     # "user" | "project"
    project: str | None = None     # project key for project facts
    project_path: str | None = None
    created: float = field(default_factory=time.time)
    source: str = "agent"          # "agent" (Grid saved it) | "user" (added in the app)


class FactStore:
    def __init__(self, path: Path | None = None):
        self.path = path or (_root() / "facts.json")

    def all(self) -> list[Fact]:
        out = []
        for raw in _read_json(self.path, []):
            try:
                out.append(Fact(**raw))
            except TypeError:
                continue
        return out

    def for_context(self, workspace: str | None) -> tuple[list[Fact], list[Fact]]:
        key = project_key(workspace) if workspace else None
        facts = self.all()
        return ([f for f in facts if f.scope == "user"],
                [f for f in facts if f.scope == "project" and key and f.project == key])

    def add(self, text: str, scope: str = "user", workspace: str | None = None, source: str = "agent") -> Fact:
        text = " ".join((text or "").split())
        if not text:
            raise MemoryError_("nothing to remember")
        if len(text) > MAX_FACT:
            raise MemoryError_(f"keep a memory under {MAX_FACT} characters - save the gist")
        if looks_secret(text):
            raise MemoryError_("that looks like a password or key - Grid never stores those")
        if scope not in ("user", "project"):
            raise MemoryError_("scope must be 'user' or 'project'")
        if scope == "project" and not workspace:
            raise MemoryError_("project memories need a project")
        with _LOCK:
            facts = self.all()
            key = project_key(workspace) if scope == "project" else None
            for f in facts:   # same thing said twice: keep one
                if f.scope == scope and f.project == key and f.text.lower() == text.lower():
                    return f
            fact = Fact(id=uuid.uuid4().hex[:8], text=text, scope=scope, project=key,
                        project_path=os.path.realpath(workspace) if key else None, source=source)
            facts.append(fact)
            _write_json(self.path, [asdict(f) for f in facts])
        return fact

    def update(self, fid: str, text: str) -> Fact:
        text = " ".join((text or "").split())
        if not text or looks_secret(text) or len(text) > MAX_FACT:
            raise MemoryError_("that can't be saved (empty, too long, or looks like a secret)")
        with _LOCK:
            facts = self.all()
            for f in facts:
                if f.id == fid:
                    f.text = text
                    _write_json(self.path, [asdict(x) for x in facts])
                    return f
        raise MemoryError_(f"no memory {fid}")

    def forget(self, fid: str) -> Fact:
        with _LOCK:
            facts = self.all()
            hit = next((f for f in facts if f.id == fid), None)
            if hit is None:
                raise MemoryError_(f"no memory {fid}")
            _write_json(self.path, [asdict(f) for f in facts if f.id != fid])
        return hit


# -- chat archive -----------------------------------------------------------------

@dataclass
class Turn:
    user: str
    reply: str
    outcome: str = ""
    changed: list[str] = field(default_factory=list)
    at: float = field(default_factory=time.time)


@dataclass
class ChatRecord:
    id: str
    project: str
    project_path: str
    title: str
    started: float
    updated: float
    turns: list[Turn] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> ChatRecord:
        turns = [Turn(**t) for t in d.get("turns", []) if isinstance(t, dict)]
        return cls(**{k: v for k, v in d.items() if k != "turns"}, turns=turns)


class ChatArchive:
    def __init__(self, root: Path | None = None):
        self.root = root or (_root() / "chats")

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def _load(self, key: str) -> dict[str, ChatRecord]:
        out = {}
        for cid, raw in _read_json(self._path(key), {}).items():
            try:
                out[cid] = ChatRecord.from_dict(raw)
            except (TypeError, KeyError):
                continue
        return out

    def record(self, chat_id: str, workspace: str, user: str, reply: str, *, outcome: str = "",
               changed: list[str] | None = None) -> ChatRecord:
        key = project_key(workspace)
        user_t = scrub(user.strip())[:MAX_TURN_USER]
        reply_t = scrub((reply or "").strip())[:MAX_TURN_REPLY]
        with _LOCK:
            chats = self._load(key)
            rec = chats.get(chat_id)
            now = time.time()
            if rec is None:
                title = " ".join(user_t.split())[:80] or "Untitled chat"
                rec = ChatRecord(id=chat_id, project=key, project_path=os.path.realpath(workspace),
                                 title=title, started=now, updated=now)
                chats[chat_id] = rec
            rec.turns.append(Turn(user=user_t, reply=reply_t, outcome=outcome, changed=list(changed or [])[:50]))
            rec.updated = now
            if len(chats) > MAX_CHATS_PER_PROJECT:
                for old in sorted(chats.values(), key=lambda c: c.updated)[: len(chats) - MAX_CHATS_PER_PROJECT]:
                    chats.pop(old.id, None)
            _write_json(self._path(key), {k: asdict(v) for k, v in chats.items()})
        return rec

    def chats(self, workspace: str) -> list[ChatRecord]:
        return sorted(self._load(project_key(workspace)).values(), key=lambda c: c.updated, reverse=True)

    def get(self, workspace: str, chat_id: str) -> ChatRecord | None:
        return self._load(project_key(workspace)).get(chat_id)

    def rename(self, workspace: str, chat_id: str, title: str) -> None:
        key = project_key(workspace)
        with _LOCK:
            chats = self._load(key)
            if chat_id in chats:
                chats[chat_id].title = " ".join(title.split())[:80] or chats[chat_id].title
                _write_json(self._path(key), {k: asdict(v) for k, v in chats.items()})

    def delete(self, workspace: str, chat_id: str) -> None:
        key = project_key(workspace)
        with _LOCK:
            chats = self._load(key)
            chats.pop(chat_id, None)
            _write_json(self._path(key), {k: asdict(v) for k, v in chats.items()})

    def all_projects(self) -> list[ChatRecord]:
        out = []
        if self.root.is_dir():
            for p in self.root.glob("*.json"):
                out += self._load(p.stem).values()
        return out


# -- search -----------------------------------------------------------------------

@dataclass
class Hit:
    kind: str          # fact | chat
    score: float
    text: str
    ref: dict


def _score(query: set[str], text: str) -> int:
    return len(query & _keywords(text))


def search(query: str, workspace: str | None, *, everywhere: bool = False, limit: int = 8,
           exclude_chat: str | None = None) -> list[Hit]:
    q = _keywords(query)
    if not q:
        return []
    hits: list[Hit] = []
    key = project_key(workspace) if workspace else None
    for f in FactStore().all():
        if f.scope == "project" and f.project != key and not everywhere:
            continue
        s = _score(q, f.text)
        if s:
            hits.append(Hit("fact", s + 0.5, f.text, {"id": f.id, "scope": f.scope}))
    archive = ChatArchive()
    chats = archive.all_projects() if everywhere else (archive.chats(workspace) if workspace else [])
    now = time.time()
    for c in chats:
        if c.id == exclude_chat:
            continue
        for i, t in enumerate(c.turns):
            s = _score(q, t.user) * 2 + _score(q, t.reply) + _score(q, c.title)
            if s:
                age_days = (now - t.at) / 86400
                hits.append(Hit("chat", s - min(age_days / 30, 1.0) * 0.5,
                                f"[{time.strftime('%b %d', time.localtime(t.at))} · {c.title}] You asked: {t.user[:300]}"
                                f"\nGrid: {t.reply[:500]}" + (f"\nChanged: {', '.join(t.changed[:8])}" if t.changed else ""),
                                {"chat": c.id, "turn": i, "project": c.project_path}))
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def context_prompt(workspace: str, current_chat: str | None = None, *, recent: int = 5) -> str:
    """What a new chat should know before the first message."""
    user, project = FactStore().for_context(workspace)
    parts = []
    if user:
        parts.append("WHAT YOU KNOW ABOUT THE USER (from earlier chats; use it, don't recite it):\n"
                     + "\n".join(f"- {f.text}" for f in user[-40:]))
    if project:
        parts.append("NOTES FOR THIS PROJECT:\n" + "\n".join(f"- {f.text}" for f in project[-40:]))
    past = [c for c in ChatArchive().chats(workspace) if c.id != current_chat][:recent]
    if past:
        lines = []
        for c in past:
            last = c.turns[-1] if c.turns else None
            when = time.strftime("%b %d", time.localtime(c.updated))
            tail = f" -> {last.outcome}" if last and last.outcome else ""
            lines.append(f"- {when}: {c.title}{tail}" + (f" (last: {last.reply[:160]})" if last and last.reply else ""))
        parts.append("RECENT CHATS IN THIS PROJECT (use the memory tool's recall to see more):\n" + "\n".join(lines))
    return "\n\n".join(parts)


def recall_for_task(task: str, workspace: str, current_chat: str | None) -> str:
    """Past-chat snippets relevant to this message (other chats only)."""
    hits = [h for h in search(task, workspace, limit=3, exclude_chat=current_chat) if h.kind == "chat" and h.score >= 2]
    if not hits:
        return ""
    return "FROM EARLIER CHATS (may be relevant):\n" + "\n\n".join(h.text for h in hits)


MEMORY_INSTRUCTION = """\
MEMORY: You remember across chats. Facts about the user, notes for this project and summaries of past chats are
above when they exist. Use the `memory` tool:
- remember: when the user tells you something lasting about themselves (name, goals, what they're learning, how
  they like to work) or asks you to remember something, save one short fact. Use scope "project" for things only
  true of this project (conventions, decisions, where things live). Never save passwords, keys, health details,
  ages or anything they ask you not to keep.
- recall: when the user refers to earlier work ("like last time", "that bug from yesterday") or you need context
  you don't have. Set everywhere=true to search other projects too.
- forget: when they ask you to forget something (use the id from recall/list)."""
