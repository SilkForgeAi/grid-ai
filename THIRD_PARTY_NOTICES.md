# Third-party notices

Grid-owned code is MIT-licensed (see LICENSE). It includes or depends on third-party
components that keep their own licenses. Their copyright notices and license
texts must stay with any copy of Grid that includes them.

| Component | Used for | License |
|---|---|---|
| OpenHands SDK / tools (openhands-sdk, openhands-tools) | agent engine | MIT - github.com/OpenHands/software-agent-sdk |
| browser-use | Grid's own browser | MIT |
| Electron | desktop app shell | MIT |
| Monaco Editor | code editor | MIT - `src/grid/server/static/vendor/monaco/LICENSE` |
| xterm.js | terminal | MIT - `src/grid/server/static/vendor/xterm/LICENSE` |
| Inter | interface font | SIL Open Font License 1.1 - `vendor/fonts/OFL-Inter.txt` |
| JetBrains Mono | code font | SIL Open Font License 1.1 - `vendor/fonts/OFL-JetBrainsMono.txt` |
| uv | installs Grid's engine | MIT / Apache-2.0 (dual) |
| Python packages (litellm, starlette, uvicorn, httpx, reportlab, python-docx, openpyxl, python-pptx, pypdf, pillow, beautifulsoup4 and their dependencies) | engine features | each package's own license, shipped in its `*.dist-info` folder |

Before a public release, run a license scan of the full dependency tree
(for example `pip-licenses` for Python and `license-checker` for the desktop app)
and include the generated list with the download.


The current dependency scan and unresolved distribution obligations are recorded
in [docs/release/LICENSE_REVIEW.md](docs/release/LICENSE_REVIEW.md). Copies of
available dependency license texts are packaged under `Resources/notices`.
`lmnr-claude-code-proxy` is a transitive dependency with a proprietary license;
public binary redistribution has not been approved. The distribution script
fails closed until the recorded blockers have been resolved.

The bundled Monaco editor keeps its upstream MIT notices. Grid renames the unused
provider-specific icon registration to the neutral `gridAgent` identifier in the
vendored worker bundles.
