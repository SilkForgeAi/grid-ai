"""Stage a reviewed current-source snapshot without local state or Git history."""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
ROOT_FILES = {
    ".env.example", ".gitattributes", ".gitignore", "GRID.md", "LICENSE", "README.md",
    "RUNBOOK.md", "SAFETY.md", "SECURITY.md", "SUPPORT.md", "THIRD_PARTY_NOTICES.md",
    "CONTRIBUTING.md", "pyproject.toml",
}
SOURCE_DIRS = {"src", "tests", "examples", "sandbox", "scripts", "desktop", "app", ".github", "release-public"}
PUBLIC_RELEASE_DOCS = {
    "RELEASE.md", "WINDOWS.md", "LICENSE_REVIEW.md", "distribution-review.json",
    "policy-evaluation.json", "python-licenses.json", "desktop-licenses.json",
}
PRIVATE_PARTS = {
    ".git", ".grid", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    "node_modules", "dist", "engine", ".ds_store", "logs", "conversations",
}
PRIVATE_SUFFIXES = {
    ".pyc", ".log", ".whl", ".p12", ".pfx", ".pem", ".key", ".p8",
    ".keychain-db", ".mobileprovision", ".gguf", ".safetensors", ".pt", ".pth",
    ".zip", ".dmg", ".exe", ".msi",
}


def allowed(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return False
    if any(p.lower() in PRIVATE_PARTS or p.lower().endswith(".app") for p in path.parts):
        return False
    if path.suffix.lower() in PRIVATE_SUFFIXES or " 2." in path.name:
        return False
    if path.name.startswith(".env") and name != ".env.example":
        return False
    if path.name.lower() in {"models.json", "settings.json", "credentials.json", "cookies.json"}:
        return False
    return (
        name in ROOT_FILES
        or path.parts[0] in SOURCE_DIRS
        or (path.parts[:2] == ("docs", "release") and path.name in PUBLIC_RELEASE_DOCS)
    )


def prepare(destination: Path, *, root: Path = ROOT) -> int:
    root, destination = root.resolve(), destination.resolve()
    if destination == root or root in destination.parents:
        raise ValueError("Public staging must be outside the source checkout")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Public staging directory must be empty")
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=root
    ).decode().split("\0")
    selected = []
    for name in sorted(set(filter(None, names))):
        if not allowed(name):
            continue
        source = root / name
        if source.is_symlink() or root not in source.resolve().parents:
            raise ValueError(f"Refusing source link outside snapshot: {name}")
        if source.is_file():
            selected.append((source, destination / name))
    for source, target in selected:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return len(selected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    print(f"Staged {prepare(parser.parse_args().destination)} source/document files; no private Git history copied")
