"""Check that a desktop artifact includes the current engine and safety assets."""

import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path

app = Path(sys.argv[1])
resources = app / "Contents/Resources"
assert (app / "Contents/Info.plist").is_file()
assert (resources / "app.asar").is_file()
with (resources / "app.asar").open("rb") as source_archive:
    header = struct.unpack("<4I", source_archive.read(16))
    entries = json.loads(source_archive.read(header[3]))["files"]
    for name in ("main.js", "preload.js", "engine-bundle.cjs"):
        assert name in entries, f"Required desktop startup file missing: {name}"
engine = resources / "engine"
wheels = list(engine.glob("grid_ai-*.whl"))
assert len(wheels) == 1, "Expected exactly one Grid engine wheel"
source = Path("desktop/engine") / wheels[0].name
assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(wheels[0].read_bytes()).digest()
with zipfile.ZipFile(wheels[0]) as archive:
    for name in ("grid/safety.py", "grid/execution.py", "grid/server/static/studio.css", "grid/server/static/workshop.css", "grid/server/static/particle-field.js", "grid/server/static/particle-backboard.js", "grid/server/static/particle-lab.js", "grid/server/static/particle-lab.css", "grid/server/static/beginner-guide.js", "grid/server/static/scroll-follow.js", "grid/server/static/grid-mark.svg"):
        assert name in archive.namelist(), name
assert (engine / "uv").is_file()
assert (resources / "notices").is_dir()
assert (resources / "THIRD_PARTY_NOTICES.md").is_file()
assert (resources / "SAFETY.md").is_file()
print("Desktop bundle and engine contents verified")
