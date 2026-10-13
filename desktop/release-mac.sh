#!/usr/bin/env bash
# Distribution build. Never falls back to an unsigned/ad-hoc release.
set -euo pipefail
cd "$(dirname "$0")"
python3 ../scripts/release/check_distribution.py
: "${GRID_SIGN_IDENTITY:?Set your Developer ID Application identity}"
: "${GRID_NOTARY_PROFILE:?Set an existing notarytool Keychain profile name}"
[[ "$GRID_SIGN_IDENTITY" == 'Developer ID Application:'* ]] || { echo 'Developer ID Application identity required' >&2; exit 1; }
security find-identity -v -p codesigning | grep -F -- "$GRID_SIGN_IDENTITY" >/dev/null || { echo 'Signing identity unavailable' >&2; exit 1; }
ARCH="$(uname -m)"; [[ "$ARCH" == arm64 ]] || ARCH=x64
npm ci --no-audit --no-fund
bash build/bundle_engine.sh "$ARCH"
if [[ "$ARCH" == arm64 ]]; then npm run package:mac; else npm run package:mac-intel; fi
APP="../dist/Grid-darwin-$ARCH/Grid.app"
# Remove Finder build metadata only; do not alter Gatekeeper protections.
xattr -dr com.apple.FinderInfo "$APP" 2>/dev/null || true
xattr -dr com.apple.ResourceFork "$APP" 2>/dev/null || true
node sign-mac.cjs "$APP"
codesign --verify --deep --strict "$APP"
ZIP="../dist/Grid-$ARCH-notary.zip"
ditto -c -k --keepParent "$APP" "$ZIP"
RESULT="../dist/notary-$ARCH.json"
xcrun notarytool submit "$ZIP" --keychain-profile "$GRID_NOTARY_PROFILE" --wait --output-format json > "$RESULT"
python3 - "$RESULT" <<'PY'
import json, sys
result=json.load(open(sys.argv[1]))
if result.get('status') != 'Accepted':
    raise SystemExit('Apple did not accept this build. Review the notarization log.')
PY
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
spctl --assess --type execute --verbose=2 "$APP"
ditto -c -k --keepParent "$APP" "../dist/Grid-$ARCH.zip"
python3 ../scripts/release/check_app_only.py --allow-source "../dist/Grid-$ARCH.zip"
shasum -a 256 "../dist/Grid-$ARCH.zip" > "../dist/Grid-$ARCH.zip.sha256"
echo "Signed, notarized and stapled: dist/Grid-$ARCH.zip"
