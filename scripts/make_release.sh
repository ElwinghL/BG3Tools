#!/usr/bin/env bash
# Empaquette une release distribuable du TUI (bg3_mod_tui/, scripts de
# lancement, doc) en zip, et pose le tag git correspondant à la version
# lue dans pyproject.toml.
#
# Usage : ./scripts/make_release.sh
# Le zip est écrit dans dist/bg3-mod-tui-vX.Y.Z.zip (dist/ est ignoré par
# git — voir .gitignore).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

VERSION="$(python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")"
TAG="v${VERSION}"
DIST_DIR="$ROOT_DIR/dist"
STAGE_DIR="$(mktemp -d)"
ARCHIVE_NAME="bg3-mod-tui-${TAG}.zip"

trap 'rm -rf "$STAGE_DIR"' EXIT

if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo "Le tag $TAG existe déjà (version déjà taguée dans pyproject.toml ?)." >&2
    exit 1
fi

echo "Préparation de la release $TAG..."
PKG_DIR="$STAGE_DIR/bg3-mod-tui-${TAG}"
mkdir -p "$PKG_DIR"

cp -r bg3_mod_tui "$PKG_DIR/"
find "$PKG_DIR/bg3_mod_tui" -type d -name "__pycache__" -exec rm -rf {} +
cp pyproject.toml README.md .env.example run.sh run.bat "$PKG_DIR/"

mkdir -p "$DIST_DIR"
(cd "$STAGE_DIR" && zip -qr "$DIST_DIR/$ARCHIVE_NAME" "bg3-mod-tui-${TAG}")

git tag -a "$TAG" -m "bg3-mod-tui $VERSION"

echo "OK :"
echo "  - $DIST_DIR/$ARCHIVE_NAME"
echo "  - tag git $TAG créé (pense à 'git push origin $TAG')"
