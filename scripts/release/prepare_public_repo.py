"""Stage only explicitly public documents in a fresh directory, never source history."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_FILES = ("README.md", "SUPPORT.md")


def prepare(destination: Path) -> None:
    destination = destination.resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError("Public staging must be outside the source checkout")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Public staging directory must be empty")
    for name in PUBLIC_FILES:
        shutil.copyfile(ROOT / "release-public" / name, destination / name)
    shutil.copyfile(ROOT / "LICENSE", destination / "LICENSE")
    print(f"Staged {len(PUBLIC_FILES) + 1} public documents; no source or Git history copied")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    prepare(parser.parse_args().destination)
