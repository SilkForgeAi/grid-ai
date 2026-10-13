# Contributing to Grid

Grid is an MIT-licensed project for helping people learn to code and enjoy building.
Beginner questions, documentation improvements, small bug fixes, and clear tests
are welcome. Open an issue before a large change so we can agree on the approach.

## Run locally

Clone the repository and follow the root README for Python setup. Use Python 3.12+,
git, and tmux. For the native app, follow desktop/README.md. Each contributor supplies
their own model credentials or local model; no API key is needed for scripted tests.

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
node --test tests/ui/*.test.cjs desktop/*.test.cjs
python scripts/release/scan_secrets.py
```

Docker integration tests require Docker and the reviewed local sandbox image; see
SAFETY.md and docs/release/RELEASE.md. Environment-dependent tests may be skipped
when those prerequisites are unavailable.

## Make a useful change

Keep pull requests focused. Explain the problem, the change, and the checks you ran.
Add a regression test for a bug fix. Preserve the rule that RED actions need human
approval and hard-blocked categories cannot be pre-approved. Do not weaken safety
checks to make a test pass. Follow GRID.md for engine architecture and test guidance.

Never commit credentials, personal profiles, conversations, logs, project contents,
local model weights, signing certificates, or installed engines. Use placeholders
in examples. Report vulnerabilities privately as described in SECURITY.md.

Contributions are provided under the repository's MIT license. Third-party code
keeps its original license and attribution; include required notices.
