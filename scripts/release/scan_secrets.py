"""Conservative current-source and Git-history secret-pattern scan.

Prints paths/object IDs only, never matched values. Does not replace GitHub's
secret scanning or detect every provider's credential format.
"""

import re
import subprocess
from pathlib import Path

PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:sk-proj-|sk-ant-)[A-Za-z0-9_-]{20,}"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
]
SYNTHETIC = {b"sk-ant-abcdefghijklmnop1234"}


def suspicious(data):
    if b"\0" in data:
        return False
    return any(match.group() not in SYNTHETIC for pattern in PATTERNS for match in pattern.finditer(data))


def main():
    names = (
        subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
        .decode()
        .split("\0")
    )
    hits = []
    count = 0
    for name in names:
        # Untracked sync-conflict copies are not shipping source and may be
        # cloud placeholders. Preserve them rather than reading/publishing them.
        if not name or name.endswith(" 2.py"):
            continue
        p = Path(name)
        if p.is_file():
            count += 1
            if suspicious(p.read_bytes()):
                hits.append(name)
    objects = subprocess.check_output(["git", "rev-list", "--objects", "--all"]).decode().splitlines()
    for item in objects:
        oid, _, name = item.partition(" ")
        if subprocess.check_output(["git", "cat-file", "-t", oid]).strip() != b"blob":
            continue
        if suspicious(subprocess.check_output(["git", "cat-file", "blob", oid])):
            hits.append(f"history:{oid[:12]}:{name}")
    if hits:
        raise SystemExit("Review secret-pattern candidates (values withheld):\n" + "\n".join(sorted(set(hits))))
    print(f"No known secret-pattern matches in {count} current files and Git history.")


if __name__ == "__main__":
    main()
