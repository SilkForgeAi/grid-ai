"""Deterministic risk rules — Grid's own RED/YELLOW floor.

The SDK asks the model to label each action's risk. A model can mislabel
`rm -rf` or `git push --force` as LOW, so the safety invariant ("RED never
auto-runs") can't rest on the model's label alone. These rules classify actions
by what they *are*, with no model involved, and GridSecurityAnalyzer takes the
worse of (model label, rule label). Rules can only raise risk, never lower it.

Also provides `is_read_only`, used by plan mode to let investigation run while
blocking anything that changes state.

Pure Python, no SDK import.
"""

from __future__ import annotations

import contextvars
import os
import re
import shlex
from dataclasses import dataclass, field

from grid.tiers import GridTier

_ORDER = {GridTier.UNKNOWN: -1, GridTier.GREEN: 0, GridTier.YELLOW: 1, GridTier.RED: 2}


def worse(a: GridTier, b: GridTier) -> GridTier:
    """The more dangerous of two tiers. UNKNOWN loses to any concrete tier."""
    return a if _ORDER[a] >= _ORDER[b] else b


@dataclass
class RuleVerdict:
    tier: GridTier = GridTier.GREEN
    reasons: list[str] = field(default_factory=list)
    # RED categories hit (see RED_CATEGORIES). Autonomous mode can run a RED
    # action only when every category it hits was pre-approved by the user.
    categories: set[str] = field(default_factory=set)

    def raise_to(self, tier: GridTier, reason: str, category: str | None = None) -> None:
        self.tier = worse(self.tier, tier)
        self.reasons.append(reason)
        if tier is GridTier.RED:
            self.categories.add(category or "other")


# RED categories a user may pre-approve for autonomous runs (--allow NAME).
ALLOWABLE_RED = {
    "delete": "recursive deletes inside the project (rm -rf, git clean)",
    "git-history": "discarding or rewriting git work (reset --hard, checkout ., branch -D)",
    "push": "git push (including --force)",
    "publish": "publishing packages (npm publish, twine upload, ...)",
    "deploy": "deploys and infrastructure/cloud changes",
    "network-exec": "piping a download into a shell",
    "permissions": "recursive chmod/chown inside the project",
    "model-flagged": "actions the model itself labeled HIGH risk",
}
# Never runnable unattended, whatever was pre-approved. A human can still
# approve them one at a time at the prompt.
HARD_BLOCKED_RED = {
    "root": "running as root (sudo)",
    "disk": "formatting or raw-writing disks",
    "credentials": "touching credentials or secrets files",
    "outside-project": "writing outside the project folder",
    "system": "power control, system services, scheduled jobs",
    "git-internals": "editing .git internals",
    "computer-sensitive": "sending, buying, deleting or passwords while controlling other apps",
    "other": "unclassified high-risk actions",
}


# --- terminal command rules -------------------------------------------------

_RED_PATTERNS: list[tuple[str, str, str]] = [
    (r"\brm\s+(?:-\w*[rR]\w*\s+-\w*f|-\w*f\w*\s+-\w*[rR]|-\w*[rR]\w*f|-\w*f\w*[rR]|--recursive|-[rR]\b)",
     "recursive delete", "delete"),
    (r"\bfind\b[^\n|;&]*\s-(?:delete\b|exec(?:dir)?\s+rm\b)", "recursive delete", "delete"),
    (r"\bsudo\b", "runs as root", "root"),
    (r"\bgit\s+push\b", "pushes to a remote", "push"),
    (r"\bgit\s+reset\s+--hard\b", "discards git work", "git-history"),
    (r"\bgit\s+clean\s+-\w*f", "deletes untracked files", "delete"),
    (r"\bgit\s+(?:checkout|restore)\s+(?:--\s+)?\.(?:\s|$)", "discards working-tree changes", "git-history"),
    (r"\bgit\s+branch\s+-D\b", "force-deletes a branch", "git-history"),
    (r"\bgit\s+filter-(?:branch|repo)\b", "rewrites git history", "git-history"),
    (r"\b(?:curl|wget)\b[^|]*\|\s*(?:sudo\s+)?(?:(?:ba|z|da|k)?sh|python3?|node|perl|ruby)\b",
     "pipes a download into a shell", "network-exec"),
    (r"\bmkfs(?:\.\w+)?\b", "formats a filesystem", "disk"),
    (r"\bdd\b[^\n]*\bof=/dev/", "raw disk write", "disk"),
    (r"\bchmod\s+-R\b", "recursive permission change", "permissions"),
    (r"\bchown\s+-R\b", "recursive ownership change", "permissions"),
    (r"\b(?:npm|pnpm|yarn)\s+publish\b", "publishes a package", "publish"),
    (r"\btwine\s+upload\b", "publishes a package", "publish"),
    (r"\b(?:poetry|uv|cargo|gem)\s+publish\b", "publishes a package", "publish"),
    (r"\b(?:vercel|netlify|fly|flyctl|heroku)\b[^\n]*\b(?:deploy|--prod)\b", "deploys", "deploy"),
    (r"\bkubectl\s+(?:apply|delete|scale|rollout)\b", "changes a cluster", "deploy"),
    (r"\bterraform\s+(?:apply|destroy)\b", "changes infrastructure", "deploy"),
    (r"\b(?:aws|gcloud|az)\s+\S+", "calls a cloud provider CLI", "deploy"),
    (r"\bdocker\s+(?:push|system\s+prune|rm|rmi)\b", "pushes or deletes containers/images", "deploy"),
    (r"(?:~|\$HOME)/\.(?:ssh|aws|gnupg|config/gcloud)\b|/\.ssh/|\bid_rsa\b|\bid_ed25519\b",
     "touches credentials", "credentials"),
    (r"\b(?:shutdown|reboot|halt)\b", "power control", "system"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb", "system"),
    (r"\bcrontab\b|\blaunchctl\b|\bsystemctl\b", "changes system services", "system"),
]

_YELLOW_PATTERNS: list[tuple[str, str]] = [
    (r"\bpip3?\s+install\b|\buv\s+(?:pip\s+install|add)\b|\bpoetry\s+add\b",
     "installs Python packages"),
    (r"\b(?:npm|pnpm|yarn|bun)\s+(?:install|i|add)\b", "installs JS packages"),
    (r"\b(?:brew|apt|apt-get|dnf|yum|pacman)\s+install\b", "installs system packages"),
    (r"\bcargo\s+(?:install|add)\b|\bgo\s+get\b|\bgem\s+install\b", "installs packages"),
    (r"\b(?:curl|wget|http|nc|ssh|scp|rsync)\b", "network access"),
    (r"\bgit\s+(?:commit|merge|rebase|cherry-pick|stash|tag|checkout\s+-b|switch)\b",
     "changes git history/branches"),
    (r"\bgit\s+(?:pull|fetch|clone)\b", "network access via git"),
    (r"\brm\b", "deletes files"),
    (r"\bmv\b", "moves/renames files"),
    (r"\bdocker\b", "runs containers"),
    (r"\bkill(?:all)?\b|\bpkill\b", "kills processes"),
    (r"\bchmod\b|\bchown\b", "changes permissions"),
    (r"\bexport\s+\w*(?:KEY|TOKEN|SECRET|PASSWORD)\w*=", "handles a secret"),
    (r"\.env\b", "touches a .env file"),
]

_RED_RE = [(re.compile(p, re.IGNORECASE), why, cat) for p, why, cat in _RED_PATTERNS]
_YELLOW_RE = [(re.compile(p, re.IGNORECASE), why) for p, why in _YELLOW_PATTERNS]

_ABS_PATH_RE = re.compile(r"(?:^|[\s=>'\"])(/[^\s'\";|&>]+|~[^\s'\";|&>]*)")
_SAFE_ABS_PREFIXES = ("/dev/null", "/tmp/", "/tmp", "/dev/stdout", "/dev/stderr", "/usr/bin/",
                      "/bin/", "/usr/local/bin/", "/opt/homebrew/bin/")


# Folders the user granted Grid (grid.access) count as "inside" while classifying.
_EXTRA_ROOTS: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("grid_extra_roots", default=())


def _inside_one(path: str, root: str) -> bool:
    root = os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _inside(path: str, workspace: str) -> bool:
    path = os.path.realpath(os.path.expanduser(path))
    return _inside_one(path, workspace) or any(_inside_one(path, r) for r in _EXTRA_ROOTS.get())


def classify_command(command: str, workspace: str | None = None) -> RuleVerdict:
    """Classify a shell command. Never returns UNKNOWN: an unrecognized command
    is GREEN here and the model's label (or confidence) decides."""
    v = RuleVerdict()
    cmd = command or ""
    # Git accepts global options before its verb. Scan a normalized spelling
    # as well, so `git -C repo push` cannot evade the same rule as `git push`.
    normalized = []
    for segment in re.split(r"&&|\|\||[;|\n]", cmd):
        try:
            words = shlex.split(segment)
        except ValueError:
            v.raise_to(GridTier.RED, "unparseable shell command", "other")
            continue
        if words and os.path.basename(words[0]) == "git":
            i = 1
            while i < len(words) and words[i].startswith("-"):
                option = words[i]
                if option in ("-c", "--config-env") or option.startswith(("--config-env=", "--exec-path")):
                    v.raise_to(GridTier.RED, "changes git execution configuration", "other")
                i += 2 if option in ("-C", "-c", "--git-dir", "--work-tree", "--config-env") else 1
            normalized.append("git " + " ".join(words[i:]))
        if words:
            head = os.path.basename(words[0])
            if (re.fullmatch(r"python(?:\d+(?:\.\d+)*)?|node|ruby|perl|php|lua|(?:ba|z|da|k)?sh", head)
                    and any(w in ("-c", "-e", "--eval", "-Command", "-EncodedCommand") for w in words[1:])):
                v.raise_to(GridTier.RED, "inline code has unrestricted host access", "other")
            if "$(" in segment or "`" in segment:
                v.raise_to(GridTier.RED, "shell substitution can execute hidden commands", "other")
    scanned = cmd + "\n" + "\n".join(normalized)
    for rx, why, cat in _RED_RE:
        if rx.search(scanned):
            v.raise_to(GridTier.RED, why, cat)
    for rx, why in _YELLOW_RE:
        if rx.search(scanned):
            v.raise_to(GridTier.YELLOW, why)
    if workspace:
        writes_out = _writes_outside(cmd, workspace)
        if writes_out:
            v.raise_to(GridTier.RED, f"writes outside the project ({writes_out})", "outside-project")
    return v


_WRITE_VERBS = re.compile(r"\b(?:rm|mv|cp|tee|touch|mkdir|rmdir|ln|truncate|sed\s+-i|chmod|chown)\b")


_WRITE_HEADS = {"rm", "mv", "cp", "tee", "touch", "mkdir", "rmdir", "ln", "truncate", "sed", "chmod", "chown", "install"}
_HOME_VAR = re.compile(r"\$\{HOME\}|\$HOME\b")
_CD_RE = re.compile(r"(?:^|[;&|(]\s*)cd(?:\s+([^\s;&|)]+))?")


def _writes_outside(cmd: str, workspace: str) -> str | None:
    """Return the first path a write-ish command targets outside the workspace
    (redirect target or argument of a write verb), else None. Covers absolute
    paths, ~ and $HOME, relative paths that climb out with .., and writing after
    `cd`-ing out of the project."""
    cmd = _HOME_VAR.sub(lambda _m: os.path.expanduser("~"), cmd)
    out = _writes_outside_abs(cmd, workspace)
    if out or not _WRITE_VERBS.search(cmd) and not re.search(r">>?\s*[^\s&]", cmd):
        return out
    # relative paths that climb out of the project: redirect targets and what write verbs write to
    for m in re.finditer(r">>?\s*([^\s;|&]+)", cmd):
        t = m.group(1)
        if not t.startswith("&") and ".." in t.split("/") and not _inside(os.path.join(workspace, t), workspace):
            return t
    for seg in re.split(r"\|\||&&|;|\||\n", cmd):
        try:
            words = shlex.split(re.sub(r"\d?>>?\s*[^\s;|&]+", " ", seg))
        except ValueError:
            continue
        if not words:
            continue
        head = os.path.basename(words[0])
        if head == "sed" and not any(w.startswith("-i") or w == "--in-place" for w in words):
            continue
        if head not in _WRITE_HEADS:
            continue
        args = [w for w in words[1:] if not w.startswith("-")]
        if head in ("cp", "ln", "install"):
            args = args[-1:]          # only the destination is written
        for w in args:
            if ".." in w.split("/") and not _inside(os.path.join(workspace, w), workspace):
                return w
    # `cd somewhere-else && rm ...`: we can't know where relative writes land
    for m in _CD_RE.finditer(cmd):
        target = m.group(1)
        if target is None or target in ("~", "-"):
            return "~" if target != "-" else "(previous directory)"
        target = target.strip("'\"")
        dest = target if target.startswith(("/", "~")) else os.path.join(workspace, target)
        if not _inside(dest, workspace):
            return dest
    return None


def _writes_outside_abs(cmd: str, workspace: str) -> str | None:
    for m in re.finditer(r">>?\s*([^\s;|&]+)", cmd):
        target = m.group(1)
        if target.startswith("&"):
            continue
        if target.startswith(("/", "~")) and not target.startswith(_SAFE_ABS_PREFIXES):
            if not _inside(target, workspace):
                return target
    if _WRITE_VERBS.search(cmd):
        for m in _ABS_PATH_RE.finditer(cmd):
            p = m.group(1)
            if p.startswith(_SAFE_ABS_PREFIXES):
                continue
            if not _inside(p, workspace):
                return p
    return None


# --- file editor rules -------------------------------------------------------

_SECRET_FILE_RE = re.compile(
    r"(?:^|/)(?:\.env(?:\..*)?|id_rsa|id_ed25519|.*\.pem|.*\.key|credentials(?:\.json)?|\.netrc|\.npmrc|\.pypirc)$",
    re.IGNORECASE,
)
_CONFIG_FILE_RE = re.compile(
    r"(?:^|/)(?:package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|uv\.lock|Cargo\.lock|"
    r"go\.sum|requirements.*\.txt|pyproject\.toml|package\.json|setup\.cfg|setup\.py|Dockerfile|"
    r"docker-compose\.ya?ml|\.github/workflows/.*)$",
    re.IGNORECASE,
)


def classify_file_edit(path: str, command: str, workspace: str | None = None) -> RuleVerdict:
    v = RuleVerdict()
    if command == "view":
        if _SECRET_FILE_RE.search(path or ""):
            v.raise_to(GridTier.YELLOW, "reads a secrets file")
        return v
    if workspace and path and not _inside(path, workspace):
        v.raise_to(GridTier.RED, f"edits a file outside the project ({path})", "outside-project")
    if _SECRET_FILE_RE.search(path or ""):
        v.raise_to(GridTier.RED, "edits a secrets file", "credentials")
    if "/.git/" in (path or "") or (path or "").endswith("/.git"):
        v.raise_to(GridTier.RED, "edits git internals", "git-internals")
    if _CONFIG_FILE_RE.search(path or ""):
        v.raise_to(GridTier.YELLOW, "edits dependency/config/CI file")
    return v


# --- read-only detection (plan mode) ----------------------------------------

READ_ONLY_TOOLS = {"glob", "grep", "think", "finish", "task_tracker"}

_READ_ONLY_CMDS = {
    "ls", "cat", "head", "tail", "less", "more", "grep", "rg", "ag", "wc", "pwd", "tree",
    "file", "stat", "du", "df", "which", "type", "echo", "printf", "sort", "uniq", "cut",
    "diff", "cmp", "jq", "env", "whoami", "date", "uname", "basename", "dirname",
    "realpath", "readlink", "true", "nl", "column", "awk", "pytest", "python -m pytest",
}
_READ_ONLY_GIT = {"status", "log", "diff", "show", "branch", "remote", "blame", "ls-files",
                  "rev-parse", "describe", "shortlog", "grep"}


def _segment_read_only(seg: str) -> bool:
    seg = seg.strip()
    if not seg:
        return True
    try:
        words = shlex.split(seg)
    except ValueError:
        return False
    if not words:
        return True
    head = os.path.basename(words[0])
    if head == "git":
        sub = next((w for w in words[1:] if not w.startswith("-")), "")
        if sub == "remote":
            return words[2:] in ([], ["-v"], ["--verbose"])
        if sub == "branch" and any(w in ("-d", "-D", "-m", "-M") for w in words):
            return False
        return sub in _READ_ONLY_GIT
    if head == "find":
        return not any(w in ("-delete", "-exec", "-execdir", "-ok", "-fprint") for w in words)
    if head == "sed":
        return not any(w.startswith("-i") or w == "--in-place" for w in words)
    if head == "awk":
        return "system(" not in seg and ">" not in seg
    if head in ("python", "python3") and words[1:3] == ["-m", "pytest"]:
        return True
    if head in ("npm", "pnpm", "yarn") and len(words) > 1 and words[1] == "test":
        return True
    if head in ("cargo", "go") and len(words) > 1 and words[1] == "test":
        return True
    return head in _READ_ONLY_CMDS


def command_is_read_only(command: str) -> bool:
    cmd = command or ""
    # Output redirection to anything but /dev/null or another fd is a write.
    for m in re.finditer(r"(?<![0-9&])>>?\s*([^\s;|&]+)|\d>>?\s*([^\s;|&]+)", cmd):
        target = m.group(1) or m.group(2) or ""
        if target and not target.startswith("&") and target != "/dev/null":
            return False
    if "$(" in cmd or "`" in cmd:
        return False
    segments = re.split(r"\|\||&&|;|\||\n", cmd)
    return all(_segment_read_only(s) for s in segments)


@dataclass
class ActionInfo:
    """The bits of an SDK ActionEvent the rules need, extracted by the caller."""

    tool_name: str
    command: str | None = None      # terminal command, or file_editor sub-command
    path: str | None = None         # file_editor path


# Grid's own tools (grid.tools). They enforce folder access themselves, so the
# rules only add what the tool can't know.
GRID_TOOLS = {"memory", "web_search", "web_fetch", "create_document", "request_access", "view_image", "computer"}
_GRID_READ_ONLY = {"web_search", "web_fetch", "request_access", "view_image"}
_BROWSER_READ_ONLY = {"browser_get_state", "browser_get_content", "browser_list_tabs", "browser_get_storage"}
READ_ONLY_TOOL_NAMES = frozenset(READ_ONLY_TOOLS | _GRID_READ_ONLY | _BROWSER_READ_ONLY)


def classify_action(info: ActionInfo, workspace: str | None = None, roots: tuple[str, ...] | list[str] = ()) -> RuleVerdict:
    token = _EXTRA_ROOTS.set(tuple(roots))
    try:
        return _classify_action(info, workspace)
    finally:
        _EXTRA_ROOTS.reset(token)


def _classify_action(info: ActionInfo, workspace: str | None) -> RuleVerdict:
    if info.tool_name in GRID_TOOLS:
        v = RuleVerdict()
        if info.tool_name == "create_document" and info.path and _SECRET_FILE_RE.search(info.path):
            v.raise_to(GridTier.RED, "writes a secrets-looking file", "credentials")
        if info.tool_name == "computer":
            _classify_computer(info.command or "", v)
        return v
    if info.tool_name.startswith("browser_"):
        return _classify_browser(info)
    if info.tool_name == "terminal":
        return classify_command(info.command or "", workspace)
    if info.tool_name == "file_editor":
        return classify_file_edit(info.path or "", info.command or "", workspace)
    if not info.tool_name or info.tool_name in READ_ONLY_TOOLS:
        return RuleVerdict()
    # MCP tools, browser, anything else: the rules know nothing about them.
    v = RuleVerdict()
    v.raise_to(GridTier.YELLOW, f"external tool '{info.tool_name}'")
    return v


def _classify_computer(command: str, v: RuleVerdict) -> None:
    """Controlling the user's apps: sending, buying, deleting and passwords always need a human."""
    from grid.computer import SENSITIVE

    action, _, rest = command.partition("|")
    if action in ("screenshot", "wait"):
        return
    keys = rest.rsplit("|", 1)[-1].lower().replace(" ", "")
    if SENSITIVE.search(rest):
        v.raise_to(GridTier.RED, "may send, buy, delete or touch a password in another app", "computer-sensitive")
    if action == "key" and re.search(r"(cmd|command)\+(shift\+)?(delete|backspace)", keys):
        v.raise_to(GridTier.RED, "deletes (cmd+delete)", "computer-sensitive")
    elif action == "key" and re.search(r"(cmd|command)\+q$", keys):
        v.raise_to(GridTier.YELLOW, "quits an app")


def _classify_browser(info: ActionInfo) -> RuleVerdict:
    """Grid's own browser profile: browsing is fine; local files, secrets and storage edits are not."""
    v = RuleVerdict()
    arg = (info.command or "").strip()
    if info.tool_name == "browser_navigate" and re.match(r"^(file|chrome|about|view-source|data|javascript):", arg, re.I):
        v.raise_to(GridTier.RED, f"opens a local or browser-internal page ({arg[:60]})", "outside-project")
    if info.tool_name == "browser_type" and _looks_secret(arg):
        v.raise_to(GridTier.RED, "types something that looks like a password or key", "credentials")
    if info.tool_name == "browser_set_storage":
        v.raise_to(GridTier.YELLOW, "changes the browser's stored data")
    return v


def _looks_secret(text: str) -> bool:
    from grid.longmem import looks_secret

    return looks_secret(text) or bool(re.match(r"^(?=.*\d)(?=.*[A-Za-z])(?=.*[^\w\s]).{8,}$", text) and " " not in text)


def is_read_only(info: ActionInfo) -> bool:
    if info.tool_name in READ_ONLY_TOOL_NAMES:
        return True
    if info.tool_name == "memory":
        return info.command in ("recall", "list")
    if info.tool_name == "computer":
        return (info.command or "").split("|", 1)[0] in ("screenshot", "wait")
    if info.tool_name == "file_editor":
        return info.command == "view"
    if info.tool_name == "terminal":
        return command_is_read_only(info.command or "")
    return False
