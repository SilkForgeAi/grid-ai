#!/usr/bin/env bash
# Put Grid's engine bundle in desktop/engine/: the Grid wheel + a checksum-verified uv.
# The packaged app copies engine/ into Grid.app/Contents/Resources and, on first
# launch, builds its own engine from it in ~/.grid/engine (see main.js).
#   build/bundle_engine.sh [arm64|x64]
set -euo pipefail
cd "$(dirname "$0")/.."
UV_VERSION="0.11.32"
case "${1:-arm64}" in
  arm64) TARGET="aarch64-apple-darwin" ;;
  x64)   TARGET="x86_64-apple-darwin" ;;
  *) echo "usage: $0 [arm64|x64]"; exit 2 ;;
esac
rm -rf engine && mkdir -p engine
command -v uv >/dev/null || { echo "needs uv: https://docs.astral.sh/uv/"; exit 1; }
(cd .. && uv build --wheel -o desktop/engine)
rm -f engine/.gitignore
# func-timeout only publishes a source package; ship it prebuilt so the install never needs to build anything
uvx --from pip pip wheel --no-deps -q -w engine "func-timeout==4.3.5"
tmp="$(mktemp -d)"
base="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${TARGET}.tar.gz"
curl -fsSL -o "$tmp/uv.tgz" "$base"
curl -fsSL -o "$tmp/uv.sha256" "$base.sha256"
want="$(cut -d' ' -f1 < "$tmp/uv.sha256")"
got="$( (sha256sum "$tmp/uv.tgz" 2>/dev/null || shasum -a 256 "$tmp/uv.tgz") | cut -d' ' -f1)"
[[ "$want" == "$got" ]] || { echo "uv checksum mismatch"; exit 1; }
tar xzf "$tmp/uv.tgz" -C "$tmp"
cp "$tmp/uv-${TARGET}/uv" engine/uv
chmod +x engine/uv
rm -rf "$tmp"
ls -la engine
