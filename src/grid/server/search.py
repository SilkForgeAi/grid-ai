"""Project-wide file listing, search and replace for the app.

`list_files` respects .gitignore when the project is a git repo (falls back to a
walk that skips the usual junk folders). `search` and `replace` work line by
line, like an editor's find-in-files: a match never spans a newline, and every
replacement is re-checked against the exact text the user saw.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from grid.server.projects import HIDDEN, FileOps, ProjectError

MAX_FILES = 20_000           # file index cap
MAX_SEARCH_BYTES = 1_000_000  # skip files bigger than this
MAX_MATCHES = 2_000          # stop collecting after this many
MAX_PREVIEW = 160            # characters of context per match line
SEARCH_SECONDS = 8.0          # time budget for one search


# -- listing ------------------------------------------------------------------------

def _hidden(rel: str) -> bool:
    return any(part in HIDDEN for part in rel.split("/"))


def _inside(root: Path, rel: str) -> bool:
    """False for symlinks that lead out of the project - never read or write through those."""
    real = os.path.realpath(root / rel)
    return real.startswith(str(root) + os.sep)


def _u16(s: str) -> int:
    """Length in UTF-16 code units - what the browser and the editor count."""
    return len(s.encode("utf-16-le")) // 2


def _git_files(root: Path) -> list[str] | None:
    if not shutil.which("git") or not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             cwd=root, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    files = []
    for raw in out.stdout.split(b"\x00"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="surrogateescape")
        if _hidden(rel) or not (root / rel).is_file() or not _inside(root, rel):  # deleted-but-tracked, escaping links
            continue
        files.append(rel)
    return files


def _walk_files(root: Path) -> list[str]:
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in HIDDEN)
        base = Path(dirpath).relative_to(root).as_posix()
        for name in sorted(filenames):
            rel = name if base == "." else f"{base}/{name}"
            if name in HIDDEN or not _inside(root, rel):
                continue
            files.append(rel)
            if len(files) > MAX_FILES:   # one extra so list_files can tell it was cut off
                return files
    return files


def list_files(root: str | Path) -> dict:
    """Every file in the project (relative paths), for quick open and search."""
    root = Path(os.path.realpath(root))
    files = _git_files(root)
    if files is None:
        files = _walk_files(root)
    files.sort(key=lambda p: (p.count("/"), p.lower()))
    truncated = len(files) > MAX_FILES
    return {"files": files[:MAX_FILES], "truncated": truncated}


# -- globs --------------------------------------------------------------------------

def _glob_regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "{":
            j = pattern.find("}", i)
            if j > i:
                out.append("(?:" + "|".join(re.escape(x) for x in pattern[i + 1:j].split(",")) + ")")
                i = j + 1
                continue
            out.append(re.escape(c))
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"(?:/.*)?$")


def parse_globs(text: str | None) -> list[str]:
    return [g.strip().strip("/") for g in (text or "").split(",") if g.strip().strip("/")]


def glob_match(rel: str, pattern: str) -> bool:
    """VS Code-ish: `*.py` matches anywhere, `src` matches the folder, `src/**/*.ts` is anchored."""
    if "/" not in pattern:
        rx = _glob_regex(pattern)
        parts = rel.split("/")
        return any(rx.match(p) for p in parts)
    return bool(_glob_regex(pattern).match(rel))


# -- search -------------------------------------------------------------------------

@dataclass
class Query:
    text: str
    regex: bool = False
    case: bool = False
    word: bool = False
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Query:
        return cls(text=str(d.get("query") or d.get("text") or ""), regex=bool(d.get("regex")),
                   case=bool(d.get("case")), word=bool(d.get("word")),
                   include=parse_globs(d.get("include")), exclude=parse_globs(d.get("exclude")))

    def compile(self) -> re.Pattern:
        if not self.text:
            raise ProjectError("type something to search for")
        src = self.text if self.regex else re.escape(self.text)
        if self.word:
            src = rf"(?<![\w]){src}(?![\w])"
        try:
            rx = re.compile(src, 0 if self.case else re.IGNORECASE)
        except re.error as exc:
            raise ProjectError(f"that regex doesn't parse: {exc}") from exc
        if rx.match(""):
            raise ProjectError("that pattern matches empty text - make it more specific")
        return rx

    def wants(self, rel: str) -> bool:
        if self.include and not any(glob_match(rel, g) for g in self.include):
            return False
        return not any(glob_match(rel, g) for g in self.exclude)


def _read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_SEARCH_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _lines(text: str) -> list[tuple[str, str]]:
    """(content, line ending) pairs so a rewrite keeps \\r\\n files as they were."""
    out = []
    for raw in text.splitlines(keepends=True):
        body = raw.rstrip("\r\n")
        out.append((body, raw[len(body):]))
    return out


def _preview(line: str, start: int, end: int) -> dict:
    """Trim very long lines around the match, keeping offsets relative to `text`."""
    lead = 40
    cut = max(0, start - lead) if len(line) > MAX_PREVIEW else 0
    if cut:
        # don't start mid-word if we can help it
        sp = line.rfind(" ", cut - 10 if cut >= 10 else 0, cut)
        cut = sp + 1 if sp >= 0 else cut
    text = line[cut:cut + MAX_PREVIEW + (end - start)]
    stripped = len(text) - len(text.lstrip())
    text = text.lstrip()
    a, b = start - cut - stripped, end - cut - stripped
    # offsets in UTF-16 units so the browser highlights the right characters
    return {"text": text.rstrip(), "start": _u16(text[:a]), "end": _u16(text[:b]), "clipped_left": cut > 0}


def search(root: str | Path, q: Query, *, max_matches: int = MAX_MATCHES) -> dict:
    rx = q.compile()
    root = Path(os.path.realpath(root))
    files = list_files(root)["files"]
    deadline = time.monotonic() + SEARCH_SECONDS
    results, total, scanned, truncated = [], 0, 0, False
    for rel in files:
        if not q.wants(rel):
            continue
        if time.monotonic() > deadline:
            truncated = True
            break
        text = _read_text(root / rel)
        scanned += 1
        if text is None:
            continue
        matches = []
        for n, (line, _eol) in enumerate(_lines(text), start=1):
            for m in rx.finditer(line):
                if m.end() == m.start():
                    continue
                # col/length identify the match for replace; ecol/elength place it in the editor
                matches.append({"line": n, "col": m.start() + 1, "length": m.end() - m.start(),
                                "ecol": _u16(line[:m.start()]) + 1, "elength": _u16(m.group(0)),
                                "match": m.group(0), **_preview(line, m.start(), m.end())})
                total += 1
                if total >= max_matches:
                    break
            if total >= max_matches:
                break
        if matches:
            results.append({"path": rel, "matches": matches})
        if total >= max_matches:
            truncated = True
            break
    return {"results": results, "matches": total, "files": len(results), "scanned": scanned,
            "truncated": truncated}


# -- replace ------------------------------------------------------------------------

def _expand(rx_regex: bool, m: re.Match, replacement: str) -> str:
    """$1 / $<name> / $& / $$ in regex mode (what editors use); literal otherwise."""
    if not rx_regex:
        return replacement

    def sub(t: re.Match) -> str:
        tok = t.group(0)
        if tok == "$$":
            return "$"
        if tok == "$&" or tok == "$0":
            return m.group(0)
        name = t.group(1) or t.group(2)
        try:
            return m.group(int(name) if name.isdigit() else name) or ""
        except IndexError:  # no such group: leave the text as typed
            return tok

    return re.sub(r"\$\$|\$&|\$(\d+)|\$<(\w+)>", sub, replacement)


def _replace_line(rx: re.Pattern, line: str, n: int, want: set | None, regex: bool, replacement: str) -> tuple[str, int]:
    count = 0

    def one(m: re.Match) -> str:
        nonlocal count
        if want is not None and not any(ln == n and col == m.start() + 1 and (not txt or txt == m.group(0))
                                        for ln, col, txt in want):
            return m.group(0)
        count += 1
        return _expand(regex, m, replacement)

    return rx.sub(one, line), count


def replace(root: str | Path, q: Query, replacement: str, *, paths: list[str] | None = None,
            only: list[dict] | None = None) -> dict:
    """Replace matches on disk.

    `paths` limits it to those files; `only` (a list of {path, line, col, match})
    replaces just those exact matches and skips any whose text no longer matches
    what the user saw.
    """
    rx = q.compile()
    fo = FileOps(str(root))
    targets: dict[str, set[tuple[int, int, str]]] = {}
    if only:
        try:
            for o in only:
                targets.setdefault(str(o["path"]), set()).add((int(o["line"]), int(o["col"]), str(o.get("match") or "")))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError("each match needs a path, line and col") from exc
        files = list(targets)
    else:
        files = [str(x) for x in paths] if paths is not None else list_files(fo.root)["files"]
        files = [f for f in files if q.wants(f)]
    # resolve every path first: one bad path fails the whole request before anything is written
    resolved = [(rel, fo.resolve(rel, must_exist=True)) for rel in files]
    changed, count, skipped = [], 0, 0
    for rel, p in resolved:
        text = _read_text(p)
        if text is None:
            continue
        want = targets.get(rel)
        out, n_here = [], 0
        for n, (line, eol) in enumerate(_lines(text), start=1):
            new_line, k = _replace_line(rx, line, n, want, q.regex, replacement)
            out.append(new_line + eol)
            n_here += k
        if want is not None:
            skipped += max(0, len(want) - n_here)
        if n_here:
            new = "".join(out)
            with open(p, "w", encoding="utf-8", newline="") as fh:
                fh.write(new)
            changed.append(rel)
            count += n_here
    return {"files_changed": changed, "replacements": count, "skipped": skipped}
