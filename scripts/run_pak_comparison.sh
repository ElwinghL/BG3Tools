#!/usr/bin/env bash
# Lance la comparaison complète des lecteurs .pak (Python, Rust debug,
# Rust release, Divine.exe per-file) sur un même dossier de mods, puis
# affiche les temps totaux et croise l'exactitude via `diff`.
#
# Mode batch Divine.exe volontairement exclu (voir .claude/TODO.md #19 —
# extract-packages plante sous LSLib upstream, correctif en attente
# d'intégration côté Tools/ExportTools).
#
# Usage : ./scripts/run_pak_comparison.sh [dossier_mods] [rust_report_a_diff]
#   dossier_mods         : défaut = config bg3_appdata_dir (bg3modtools.toml)
#   rust_report_a_diff   : "debug" ou "release" (défaut "release") — variante
#                          Rust copiée vers reports/rust_report.json avant `diff`

set -euo pipefail

# Cache uv (~/.cache/uv) et .venv du projet souvent sur des filesystems
# différents ici (ex: btrfs vs ext4) — un hardlink ne peut pas traverser
# ça, uv bascule sur une copie complète avec un warning à chaque run.
# Copie explicitement demandée : même résultat, juste sans le warning.
export UV_LINK_MODE=copy

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR"

MODS_DIR="${1:-}"
RUST_VARIANT="${2:-release}"
DIVINE_EXE="Tools/ExportTools/dist/Tools/Divine.exe"
REPORTS_DIR="reports"

DIR_ARGS=()
if [ -n "$MODS_DIR" ]; then
    DIR_ARGS=(--dir "$MODS_DIR")
fi

echo "=== 1/4 Python ==="
uv run python scripts/compare_pak_reader.py run --tool python "${DIR_ARGS[@]}"

echo "=== 2/4 Divine.exe (per-file) ==="
uv run python scripts/compare_pak_reader.py run --tool divine "${DIR_ARGS[@]}" \
    --divine-exe "$DIVINE_EXE"

echo "=== 3/4 Rust (debug) ==="
uv run maturin develop --manifest-path rust/pak_reader_rs/Cargo.toml
uv run python scripts/compare_pak_reader.py run --tool rust "${DIR_ARGS[@]}" \
    --out "$REPORTS_DIR/rust_debug_report.json"

echo "=== 4/4 Rust (release) ==="
uv run maturin develop --release --manifest-path rust/pak_reader_rs/Cargo.toml
uv run python scripts/compare_pak_reader.py run --tool rust "${DIR_ARGS[@]}" \
    --out "$REPORTS_DIR/rust_release_report.json"

echo
echo "=== Temps totaux par variante ==="
for f in "$REPORTS_DIR/python_report.json" "$REPORTS_DIR/divine_report.json" \
         "$REPORTS_DIR/rust_debug_report.json" "$REPORTS_DIR/rust_release_report.json"; do
    echo "-- $f --"
    jq -r '{n: (.paks|length), idx: ([.paks[].index_or_extract_seconds]|add), content: ([.paks[].content_seconds]|add)} | "n=\(.n) index=\(.idx)s content=\(.content)s total=\(.idx+.content)s"' "$f"
done

echo
echo "=== Diff croisé (variante Rust '$RUST_VARIANT') ==="
cp "$REPORTS_DIR/rust_${RUST_VARIANT}_report.json" "$REPORTS_DIR/rust_report.json"
uv run python scripts/compare_pak_reader.py diff
