# Source and app release status

On 2026-10-13 the owner authorized Grid-owned source publication under MIT.
This supersedes the former proprietary app-only distribution plan. Publish a
reviewed current-file snapshot, not private development history. Each user brings
their own model and credentials; exclude API keys, personal settings, projects,
conversations, logs, local model weights, installed engines and signing material.

## Source publication

Run `python scripts/release/prepare_source_repo.py /private/tmp/grid-source-snapshot`
into a new empty directory outside the development checkout. Review every selected
path, scan for secrets, and copy the approved files into the public repository's
separate checkout. Never attach the private development Git history to the public
remote. The allowlist preserves source, tests, build definitions and required
notices while excluding personal state and installed dependencies.

Run the Python suite, Node UI/desktop tests, and the secret scanner before pushing.
No model API key is needed for scripted tests. MIT applies to Grid-owned code;
third-party dependencies retain their own terms. See LICENSE and THIRD_PARTY_NOTICES.md.

`prepare_public_repo.py` remains a documentation-only staging utility.
`check_app_only.py --allow-source` permits MIT Grid source in app ZIPs while still
rejecting private paths and credential files. Without the flag it retains the
legacy compiled-only check. Neither mode establishes absence of secret contents.

## Consumer app downloads

There are no supported public installers yet. Source availability does not clear
binary distribution requirements. The unresolved items in distribution-review.json
include dependency redistribution, macOS signing/notarization, Windows validation,
and broader independent safety evaluation. Build scripts fail closed on that review.
Windows limitations are recorded in WINDOWS.md. Do not advertise a Windows download
without native installation, execution, safety and upgrade tests.

Local macOS builds can use ad-hoc signing for development. A consumer distribution
uses desktop/release-mac.sh with a valid Developer ID Application certificate and
private key in the local keychain. Set GRID_SIGN_IDENTITY and GRID_NOTARY_PROFILE
to the configured identity/profile names; never commit keys or passwords. The script
requires accepted notarization, staples and validates the ticket, and verifies
Gatekeeper before emitting a ZIP/checksum. It does not upload to GitHub automatically.

## Execution boundaries

Trusted-host mode runs with the user's account permissions. It is unsuitable for
untrusted repositories or a public hosted execution service. Restricted mode must
be selected explicitly with GRID_RESTRICTED=1 and requires Docker plus an independent
policy endpoint. Follow SAFETY.md for setup and limitations. Source publication
makes the controls inspectable; it does not guarantee generated code is harmless.

Before binary releases, test first-run setup in a fresh OS user environment and
scan the exact packaged artifact. Required dependency source/notices must remain
available. Keep consumer releases separate from local build and CI artifacts.
