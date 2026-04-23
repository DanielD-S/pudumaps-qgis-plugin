#!/usr/bin/env bash
# Package the plugin as a zip ready for QGIS "Install from ZIP" or upload
# to plugins.qgis.org.
#
# Usage:  ./scripts/build.sh
# Output: dist/pudumaps-qgis-<version>.zip
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$ROOT_DIR/pudumaps_qgis"
DIST_DIR="$ROOT_DIR/dist"

VERSION=$(grep -E '^version=' "$SRC_DIR/metadata.txt" | cut -d'=' -f2 | tr -d '[:space:]')
if [[ -z "$VERSION" ]]; then
  echo "ERROR: could not read version from metadata.txt" >&2
  exit 1
fi

ZIP_NAME="pudumaps-qgis-${VERSION}.zip"
ZIP_PATH="$DIST_DIR/$ZIP_NAME"

mkdir -p "$DIST_DIR"
rm -f "$ZIP_PATH"

cd "$ROOT_DIR"
zip -r "$ZIP_PATH" pudumaps_qgis \
  -x "*/__pycache__/*" \
  -x "*.pyc" \
  -x "*/.DS_Store" \
  -x "*/.pytest_cache/*" \
  > /dev/null

echo "✓ Built $ZIP_PATH"
echo "  Install in QGIS: Extensiones → Administrar e instalar → Instalar desde ZIP"
