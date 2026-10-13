# Dependency distribution review

The inventories `python-licenses.json` and `desktop-licenses.json` describe the
installed engine and locked desktop build dependencies. They are reproducible
with `scripts/release/audit_licenses.py`; metadata is not a legal clearance.

Reviewed exceptions:

- `agent-client-protocol 0.12.1`: wheel includes Apache-2.0 license text, despite
  missing license metadata. Included in the desktop notices directory.
- `openhands-sdk` and `openhands-tools 1.54.0`: missing wheel license files and
  metadata. Their tagged upstream repository includes MIT licensing; a copy is
  included with the desktop notices.
- `func_timeout 4.3.5`: metadata says LGPLv2, while the bundled license text
  says LGPLv3. This inconsistency needs resolution before public distribution.
  Its existing wheel contains readable Python source and license text. Preserve both, allow replacement/modification
  under that license, and review source-distribution obligations before release.
- `lmnr-claude-code-proxy 0.1.24`: declares `LicenseRef-Proprietary`. Its license
  states use is subject to Laminar's terms. It is a transitive engine dependency.
  **Public binary distribution is blocked pending permission or a compatible
  dependency replacement.** No permission has been assumed.
- On 2026-10-13 the owner authorized publication of Grid-owned source under MIT.
  Third-party components keep their own licenses; MIT does not override their
  requirements. Publishing source does not clear binary redistribution blockers.

The remaining scanned metadata did not trigger the current missing-license or
copyleft/proprietary flags. This does not replace review of exceptions,
transitive dependencies, bundled Electron/Chromium notices or their obligations.
Electron's packaged notices must remain with the app.

References:
- https://github.com/OpenHands/software-agent-sdk/blob/v1.54.0/LICENSE
- https://laminar.sh/policies/terms

Public source publication uses a reviewed current-file snapshot, not private Git
history. Exclude local engines, credentials, profiles, projects, logs and models.
