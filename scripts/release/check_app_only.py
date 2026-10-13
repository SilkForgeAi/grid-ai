"""Reject Grid Python source in a proposed public app ZIP, including nested wheels.

Use --allow-source for MIT builds; path/credential-file checks still apply.
This is an accidental-source-disclosure check, not obfuscation or protection
against reverse engineering. Client-side JavaScript remains inspectable.
"""
from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path, PurePosixPath


def inspect_archive(archive: zipfile.ZipFile, *, grid_wheel=False, depth=0, allow_source=False) -> None:
    if depth > 3:
        raise ValueError("Nested archive limit exceeded")
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        parts = [p.lower() for p in path.parts]
        if path.is_absolute() or ".." in parts or any(p in (".git", ".env", ".env.local") for p in parts):
            raise ValueError(f"Private or unsafe archive path: {info.filename}")
        if path.suffix.lower() in (".p12", ".pfx", ".keychain-db", ".pem", ".key"):
            raise ValueError(f"Credential-like file: {info.filename}")
        if not allow_source and (grid_wheel or "grid" in parts) and path.suffix.lower() in (".py", ".pyc", ".pyx", ".c", ".cpp"):
            raise ValueError(f"Readable or intermediate Grid code: {info.filename}")
        if path.suffix.lower() == ".whl":
            if info.file_size > 100_000_000:
                raise ValueError("Wheel exceeds inspection limit")
            with zipfile.ZipFile(io.BytesIO(archive.read(info))) as wheel:
                inspect_archive(wheel, grid_wheel=path.name.startswith("grid_ai-"), depth=depth + 1, allow_source=allow_source)


def check(path: Path, *, allow_source=False) -> None:
    if path.suffix.lower() != ".zip" or path.is_symlink():
        raise ValueError("Expected a regular application ZIP")
    with zipfile.ZipFile(path) as archive:
        inspect_archive(archive, allow_source=allow_source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--allow-source", action="store_true", help="Allow MIT Grid code; still reject private paths and credential files")
    args = parser.parse_args()
    try:
        check(args.artifact, allow_source=args.allow_source)
    except (ValueError, zipfile.BadZipFile) as error:
        raise SystemExit(f"App-only release blocked: {error}") from error
    print("Archive path/wheel checks passed; credential contents require a separate scan" if args.allow_source else "No Grid Python source found in inspected ZIP paths/wheels; reverse engineering remains possible")
