# Grid desktop app

Grid’s native Mac learning workshop, built with Electron. It starts Grid's engine
(`grid app --no-browser`) in the background and shows Grid in its own window, with:

- a Dock icon, real menus, and keyboard shortcuts (⌘O open folder, ⌘⇧N new project,
  Play / Code / Understand workspace modes, ⌘J terminal, ⌘, settings)
- the native macOS folder picker
- API keys saved encrypted with your macOS Keychain (Settings → API keys) and passed only to
  Grid's engine. Keys exported in your shell profile work too.

## Build the Mac app

Requires Node 22+, Python 3.12+, git, tmux, and uv. On your Mac, from this folder:

```bash
bash build/bundle_engine.sh "$(uname -m | sed s/x86_64/x64/)"
./build-mac.sh          # builds the app, signs it ad-hoc, copies it to /Applications
```

The engine itself is the `grid` Python package. The app looks for it in
`~/Desktop/Grid AI/grid-ai/.venv/bin/grid`, then `~/grid-ai/.venv/bin/grid`, `~/.grid/venv/bin/grid`,
and your PATH. You can also pick it yourself from the setup screen (Help → Choose Grid Engine…).

## Develop

```bash
python3.12 -m venv ../.venv
source ../.venv/bin/activate
python -m pip install -e "..[dev]"
npm ci
GRID_BIN="$(command -v grid)" npm start
```

## Explore and learn

**Lab** opens the interactive Ember particle sculpture. Drag to turn it, adjust the
three sliders, change palettes, or pause. It runs locally without a model account,
respects Reduce Motion, and stops rendering offscreen. **Start here** explains the
first project, models, terminal commands, editing, approvals, and recovery.

The app uses a geometric G identity. Native scrolling remains responsive while
chat output streams; scrolling upward stops automatic following until you return
to the end or choose **Latest messages**.

Grid-owned source is available under MIT. These are local development builds,
signed ad hoc. A public app release still requires
the distribution review, licensing work, Mac signing/notarization, and Windows
port validation described in the release documentation. Source publication does
not clear third-party dependency redistribution obligations.
