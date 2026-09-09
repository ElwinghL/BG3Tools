#!/usr/bin/env bash
# Lance le TUI BG3 Mod Tools sur Linux/macOS.
# Crée un environnement virtuel local (.venv) si nécessaire, installe les
# dépendances, puis démarre le TUI.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d "$VENV_DIR" ]; then
    echo "Création de l'environnement virtuel (.venv)..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"

"$VENV_PYTHON" -m pip install -q --upgrade pip
"$VENV_PYTHON" -m pip install -q -e .

exec "$VENV_PYTHON" -m bg3_mod_tui "$@"
