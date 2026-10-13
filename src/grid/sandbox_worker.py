"""Stdlib-only worker mounted read-only inside the isolated container."""

import json
import subprocess
import sys
from pathlib import Path


def main():
    action = json.load(sys.stdin)
    if action["kind"] == "terminal":
        result = subprocess.run(["/bin/sh", "-c", action["command"]], check=False)
        return result.returncode
    root = Path.cwd().resolve()
    path = Path(action["path"])
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError("File is outside the isolated project")
    command = action["command"]
    if command == "view":
        text = path.read_text() if path.is_file() else "\n".join(sorted(p.name for p in path.iterdir()))
        if bounds := action.get("view_range"):
            start, end = bounds
            text = "\n".join(text.splitlines()[start - 1 : None if end == -1 else end])
        print(text[:200_000])
    elif command == "create":
        with path.open("x") as f:
            f.write(action.get("file_text") or "")
        print("File created")
    elif command == "str_replace":
        text = path.read_text()
        old = action.get("old_str") or ""
        if not old or text.count(old) != 1:
            raise ValueError("Replacement must match exactly once")
        path.write_text(text.replace(old, action.get("new_str") or "", 1))
        print("File updated")
    elif command == "insert":
        lines = path.read_text().splitlines(keepends=True)
        at = action["insert_line"]
        if at < 0 or at > len(lines):
            raise ValueError("Invalid insertion line")
        lines.insert(at, action.get("new_str") or "")
        path.write_text("".join(lines))
        print("File updated")
    else:
        raise ValueError("Unsupported command; use Grid checkpoints to undo")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
