"""Inventory installed engine dependencies and desktop build dependencies.

Run with Grid's engine Python. Reports metadata, not a legal compliance verdict.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import json
from pathlib import Path

from packaging.requirements import Requirement


def python_report():
    pending, seen, rows = ["grid-ai"], set(), []
    while pending:
        name = pending.pop()
        canonical = name.lower().replace("_", "-")
        if canonical in seen:
            continue
        seen.add(canonical)
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            rows.append({"name": name, "missing": True, "review_required": True})
            continue
        metadata = dist.metadata
        license_ = metadata.get("License-Expression") or metadata.get("License") or ""
        classifiers = [
            v.removeprefix("License :: ") for v in metadata.get_all("Classifier", []) if v.startswith("License :: ")
        ]
        texts = [
            str(f)
            for f in dist.files or []
            if ".dist-info/" in str(f) and any(k in Path(str(f)).name.lower() for k in ("license", "copying", "notice"))
        ]
        # Some legacy metadata embeds the complete license instead of an SPDX ID.
        rows.append(
            {
                "name": metadata["Name"],
                "version": dist.version,
                "license_metadata": license_,
                "license_classifiers": classifiers,
                "license_files": texts,
                "review_required": not license_ and not classifiers,
                "obligation_review": any(
                    k in license_.upper() + " ".join(classifiers).upper()
                    for k in ("GPL", "LGPL", "AGPL", "SSPL", "PROPRIETARY")
                ),
            }
        )
        for raw in dist.requires or []:
            req = Requirement(raw)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                pending.append(req.name)
    return sorted(rows, key=lambda r: r["name"].lower())


def desktop_report(root):
    lock = json.loads((root / "desktop/package-lock.json").read_text())
    rows = []
    for location, pkg in lock["packages"].items():
        if not location:
            continue
        manifest = root / "desktop" / location / "package.json"
        installed = json.loads(manifest.read_text()) if manifest.exists() else {}
        license_ = pkg.get("license") or installed.get("license") or "UNKNOWN"
        rows.append(
            {
                "name": installed.get("name") or location.split("node_modules/")[-1],
                "version": pkg.get("version"),
                "license_metadata": license_,
                "build_dependency": True,
                "review_required": license_ == "UNKNOWN",
                "obligation_review": any(k in str(license_).upper() for k in ("GPL", "SSPL")),
            }
        )
    return sorted(rows, key=lambda r: r["name"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("docs/release"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, rows in [("python", python_report()), ("desktop", desktop_report(Path.cwd()))]:
        (args.output / f"{name}-licenses.json").write_text(json.dumps(rows, indent=2) + "\n")
        flagged = [r["name"] for r in rows if r.get("review_required") or r.get("obligation_review")]
        print(f"{name}: {len(rows)} packages; metadata/obligation review: {', '.join(flagged) or 'none'}")


if __name__ == "__main__":
    main()
