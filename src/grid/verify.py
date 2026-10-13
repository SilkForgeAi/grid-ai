"""Proof of outcome: run the project's check before accepting "done".

The agent saying it finished is not evidence. Grid runs the verify command
itself (from GRID.md `verify:` or the detected test runner) and only reports a
task as verified when that command exits 0.
"""

from __future__ import annotations

import os
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass

from grid.regression import RunResult, parse_pytest_summary


@dataclass
class VerifyResult:
    command: str
    ok: bool
    exit_code: int
    output: str
    seconds: float
    summary: RunResult | None = None
    timed_out: bool = False
    cancelled: bool = False

    def tail(self, lines: int = 40) -> str:
        return "\n".join(self.output.rstrip().splitlines()[-lines:])

    def label(self) -> str:
        if self.cancelled:
            return f"`{self.command}` stopped"
        if self.timed_out:
            return f"`{self.command}` timed out"
        if self.summary is not None and not self.summary.errored:
            s = self.summary
            return f"`{self.command}` -> {s.passed} passed, {s.failed} failed"
        return f"`{self.command}` -> exit {self.exit_code}"


def run_verify(command: str, workspace: str, timeout: float = 600,
               cancel: threading.Event | None = None) -> VerifyResult:
    from grid.moderation import policy_reason, restricted_mode

    start = time.monotonic()
    cancel = cancel or threading.Event()
    if restricted_mode():
        from grid.isolation import IsolationError, run_isolated

        refusal = policy_reason(command, kind="verification")
        if refusal:
            return VerifyResult(command, False, 1, refusal, 0)
        try:
            code, output = run_isolated({'kind': 'terminal', 'command': command}, workspace,
                                        timeout=timeout, cancel=cancel)
        except IsolationError as exc:
            return VerifyResult(command, False, 1, str(exc), time.monotonic()-start,
                                cancelled=cancel.is_set(), timed_out=not cancel.is_set())
        summary = parse_pytest_summary(output)
        meaningful = summary is None or (summary.passed > 0 and summary.failed == 0 and not summary.errored)
        return VerifyResult(command, code == 0 and meaningful, code, output, time.monotonic()-start, summary)

    timed_out = cancelled = False
    # A separate process group lets Stop/timeout terminate the shell AND its
    # children. Disk-backed output avoids an unbounded pipe or RAM buffer.
    with tempfile.TemporaryDirectory(prefix="grid-verify-pyc-") as pycache, tempfile.TemporaryFile() as output_file:
        env = {**os.environ, "PYTHONPYCACHEPREFIX": pycache}
        proc = subprocess.Popen(command, shell=True, cwd=workspace, stdout=output_file,
                                stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            while proc.poll() is None:
                cancelled = cancel.is_set()
                timed_out = time.monotonic() - start >= timeout
                if cancelled or timed_out:
                    break
                cancel.wait(0.05)
        finally:
            if proc.poll() is None or cancelled or timed_out:
                # The shell can exit before a descendant; address the group.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.wait()
        output_file.seek(0, os.SEEK_END)
        size = output_file.tell()
        output_file.seek(max(0, size - 2_000_000))
        output = output_file.read().decode(errors="replace")
    summary = parse_pytest_summary(output)
    meaningful = summary is None or (summary.passed > 0 and summary.failed == 0 and not summary.errored)
    return VerifyResult(command=command, ok=proc.returncode == 0 and meaningful and not (timed_out or cancelled),
                        exit_code=proc.returncode, output=output, seconds=time.monotonic() - start,
                        summary=summary, timed_out=timed_out, cancelled=cancelled)


# --- checks the agent declares itself ----------------------------------------

_DECLARED = re.compile(r"^\s*\**VERIFY\s*:\s*\**\s*`*(.+?)`*\s*$", re.IGNORECASE | re.MULTILINE)
_TRIVIAL_HEADS = {"true", ":", "echo", "printf", "exit", "ls", "pwd", "cat", "sleep", "test", "[",
                  "whoami", "date", "env", "which", "head", "tail", "wc", "grep", "rg", "git"}


def declared_verify_command(text: str | None) -> str | None:
    """The last `VERIFY: <command>` line in the agent's final message."""
    if not text:
        return None
    matches = _DECLARED.findall(text)
    return matches[-1].strip() if matches else None


def trivial_check_reason(command: str) -> str | None:
    """Why a declared check proves nothing, or None if it looks like a real check.

    This can't prove a check is meaningful, but it refuses the obvious ways to
    fake one: no-op commands, and failures swallowed with `|| true` / `; exit 0`."""
    cmd = (command or "").strip()
    if not cmd:
        return "empty command"
    if re.search(r"\|\|\s*(?:true|:|exit\s+0)\b|;\s*(?:true|exit\s+0)\s*$", cmd):
        return "it swallows failures (|| true / exit 0)"
    try:
        words = shlex.split(cmd)
    except ValueError:
        return "it can't be parsed"
    if not words:
        return "empty command"
    head = os.path.basename(words[0])
    if head in _TRIVIAL_HEADS:
        return f"`{head}` doesn't test anything"
    if head in ("python", "python3") and len(words) >= 3 and words[1] == "-c" and \
            re.fullmatch(r"\s*(?:pass|print\(.*\)|None|0|1|True)\s*", words[2]):
        return "the inline script doesn't test anything"
    return None


def test_integrity_reason(diff: str) -> str | None:
    """Require review for deletion of test evidence or newly skipped tests.

    This deliberately flags legitimate assertion rewrites too: a human must
    inspect those before we use the changed tests as evidence of success.
    """
    test_file = False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.rsplit(" b/", 1)[-1]
            test_file = bool(re.search(r"(?:^|/)(?:tests?/|test_[^/]+\.py$)|(?:\.test|\.spec)\.[^/]+$|_test\.py$", path))
        if not test_file or line.startswith(("---", "+++")):
            continue
        if line.startswith("-") and re.search(r"\b(?:assert|expect|test_|it\s*\(|test\s*\()", line[1:]):
            return "Existing test assertions or test cases were removed or rewritten."
        if line.startswith("+") and re.search(r"\b(?:skip|skipif|xfail|xdescribe|xit)\b", line[1:]):
            return "Tests were newly skipped or marked as expected failures."
    return None
