"""Require recorded resolution of distribution blockers before signing/upload."""

import json
from pathlib import Path

review = json.loads(Path(__file__).resolve().parents[2].joinpath("docs/release/distribution-review.json").read_text())
if not review.get("approved") or review.get("blockers"):
    raise SystemExit("Distribution is blocked:\n" + "\n".join("- " + item for item in review.get("blockers", [])))
print("Recorded distribution review passed")
