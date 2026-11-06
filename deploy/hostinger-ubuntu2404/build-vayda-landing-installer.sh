#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/../.." && pwd)"
ARTIFACT="$WORKSPACE/artifacts/smart-money-hub-ops"
OUTPUT_DIR="$WORKSPACE/generated-artifacts"
OUTPUT="$OUTPUT_DIR/smh-vayda-landing-installer-v5.sh"
TEMPLATE="$SCRIPT_DIR/install-vayda-landing-installer.sh"
PATCHER="$SCRIPT_DIR/patch-vayda-landing-nginx.py"
STAGE="$(mktemp -d)"
TEMP_OUTPUT="${OUTPUT}.tmp"

cleanup() {
  rm -rf "$STAGE"
  rm -f "$TEMP_OUTPUT"
}
trap cleanup EXIT

mkdir -p "$OUTPUT_DIR"
python3 "$PATCHER" --self-test
bash -n "$TEMPLATE"

(cd "$WORKSPACE" && pnpm --filter @workspace/smart-money-hub-ops run build:landing)

BUILT="$ARTIFACT/dist/landing"
[[ -s "$BUILT/landing.html" ]] || {
  echo "ERROR: Vite did not generate landing.html." >&2
  exit 1
}
mkdir -p "$STAGE/site"
cp -a "$BUILT/." "$STAGE/site/"
mv "$STAGE/site/landing.html" "$STAGE/site/index.html"
cp "$SCRIPT_DIR/landing-public/robots.txt" "$STAGE/site/robots.txt"
cp "$SCRIPT_DIR/landing-public/sitemap.xml" "$STAGE/site/sitemap.xml"
cp "$PATCHER" "$STAGE/patch-vayda-landing-nginx.py"

(
  cd "$STAGE"
  find site -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum patch-vayda-landing-nginx.py >> SHA256SUMS
)

cp "$TEMPLATE" "$TEMP_OUTPUT"
tar -czf - -C "$STAGE" site patch-vayda-landing-nginx.py SHA256SUMS >> "$TEMP_OUTPUT"
chmod 755 "$TEMP_OUTPUT"
mv -f "$TEMP_OUTPUT" "$OUTPUT"
(cd "$OUTPUT_DIR" && sha256sum "$(basename "$OUTPUT")" > "$(basename "$OUTPUT").sha256")

bash "$OUTPUT" --check-package
echo "Created $OUTPUT"
du -h "$OUTPUT"
cat "$OUTPUT.sha256"
