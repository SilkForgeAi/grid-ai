#!/usr/bin/env bash
# Build Grid.app for this Mac and install it in /Applications.
set -euo pipefail
cd "$(dirname "$0")"
ARCH="$(uname -m)"; [[ "$ARCH" == "arm64" ]] || ARCH="x64"
command -v npm >/dev/null || { echo "Node.js is needed: brew install node"; exit 1; }
npm install --no-audit --no-fund
if [[ "$ARCH" == "arm64" ]]; then npm run package:mac; else npm run package:mac-intel; fi
APP="../dist/Grid-darwin-$ARCH/Grid.app"
# Ad-hoc sign so macOS will run it (no Apple developer account needed).
codesign --force --deep --sign - "$APP"
xattr -cr "$APP" || true
rm -rf /Applications/Grid.app
cp -R "$APP" /Applications/
echo "Installed /Applications/Grid.app - open it from Launchpad or Spotlight."
