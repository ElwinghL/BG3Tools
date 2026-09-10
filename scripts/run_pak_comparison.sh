#!/usr/bin/env bash
# Lance la comparaison complète des lecteurs .pak (Python, Rust debug,
# Rust release, Divine.exe per-file) sur un même dossier de mods, puis
# affiche les temps totaux et croise l'exactitude via `diff`.
#
# La liste des .pak est figée une seule fois au lancement (pas un `--dir`
# refait à chaque étape) et transmise telle quelle aux 4 runs, pour rester
# cohérent même si le contenu du dossier change en cours de route. Chaque
# .pak est hashé intégralement (pas d'échantillon de contenu limité).
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

# Dossier résolu une seule fois (config bg3modtools.toml si non fourni en argument).
if [ -z "$MODS_DIR" ]; then
    MODS_DIR="$(uv run python -c 'from bg3_mod_tui.config import load_config; print(load_config().appdata_mods_dir)')"
fi

# Liste des .pak figée ICI, une seule fois, plutôt que de laisser chacun des
# 4 runs suivants refaire son propre `--dir` (donc son propre scan) : si le
# contenu du dossier change entre deux runs (mod ajouté/retiré pendant le
# bench), les 4 outils doivent quand même comparer exactement le même lot.
mapfile -t PAK_FILES < <(find "$MODS_DIR" -maxdepth 1 -name '*.pak' | sort)
if [ "${#PAK_FILES[@]}" -eq 0 ]; then
    echo "Aucun .pak trouvé dans $MODS_DIR" >&2
    exit 1
fi
echo "Dossier : $MODS_DIR (${#PAK_FILES[@]} .pak figés au lancement)"

# Pas de plafond d'échantillonnage : on hash TOUTES les entrées de chaque
# .pak (pas un sous-ensemble de 60) — _pick_sample_names retourne tout dès
# que le total d'entrées est sous le plafond, donc une valeur large suffit.
SAMPLE_CAP=1000000

echo "=== 1/4 Python ==="
uv run python scripts/compare_pak_reader.py run --tool python --sample "$SAMPLE_CAP" "${PAK_FILES[@]}"

echo "=== 2/4 Divine.exe (per-file) ==="
uv run python scripts/compare_pak_reader.py run --tool divine --sample "$SAMPLE_CAP" "${PAK_FILES[@]}" \
    --divine-exe "$DIVINE_EXE"

echo "=== 3/4 Rust (debug) ==="
uv run maturin develop --manifest-path rust/pak_reader_rs/Cargo.toml
uv run python scripts/compare_pak_reader.py run --tool rust --sample "$SAMPLE_CAP" "${PAK_FILES[@]}" \
    --out "$REPORTS_DIR/rust_debug_report.json"

echo "=== 4/4 Rust (release) ==="
uv run maturin develop --release --manifest-path rust/pak_reader_rs/Cargo.toml
uv run python scripts/compare_pak_reader.py run --tool rust --sample "$SAMPLE_CAP" "${PAK_FILES[@]}" \
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
