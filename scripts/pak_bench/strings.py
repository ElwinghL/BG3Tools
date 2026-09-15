"""Textes longs (messages, labels de rapport, titres de graphes, aide CLI,
gabarits Markdown) centralisés ici plutôt qu'en littéraux inline dans le
code — lisibilité (pas de texte tronqué/wrappé au milieu de la logique) et
préparation à une future traduction (le projet a déjà des README
bilingues `.md`/`.fr.md`). Ne s'applique qu'au nouveau code de ce chantier
(`pak_bench/`, `pak_bench_cli.py`) — `compare_pak_reader.py` n'est pas
retouché au-delà de ce que son import de `pak_bench.common` nécessitait
déjà.
"""

from __future__ import annotations

CAPABILITY_MATRIX_MD = """\
| Capacité | Divinity.exe (LSLib) | bg3pythonpaklib | bg3rustpaklib |
|---|---|---|---|
| Lecture pak (index, extraction) | Oui | Oui | Oui |
| Lecture batch (N pak) | Oui (1 process/pak, coût Wine/pak) | Oui (in-process) | Oui (in-process) |
| Création pak (from scratch) | Oui | Non (lecture seule) | Oui |
| Édition pak | Oui (extract/modifier/recreate) | Non | Oui (idem) |
| Archives solides, API async, .loca | Partiel | Non | Oui |

Les cases "Non" ne sont pas mesurées en perf — juste actées comme écart
fonctionnel, avec pointeur vers `.claude/TODO.md` §1f-1i.
"""

# -- report.py : Markdown --------------------------------------------------

REPORT_TITLE = "# Rapport de benchmark — outils .pak BG3"

REPORT_INTRO = (
    "Généré par `scripts/pak_bench_cli.py report`. Méthodologie : chaque "
    "outil est mesuré **dans son jus** (perf native/brute, sans pont "
    "intermédiaire) ET, quand c'est pertinent, dans le **pipeline réel** "
    "de BG3Tools (binding FFI, subprocess Wine/Proton) — voir la colonne "
    "dédiée plutôt qu'un chiffre mélangé."
)

SECTION_CAPABILITY_MATRIX = "## Matrice de capacités"
SECTION_READ = "## Lecture (single + batch)"
SECTION_CREATE_EDIT = "## Création / édition (single + batch)"
SECTION_LIMITATIONS = "## Limitations de cette passe"

READ_TABLE_EMPTY = (
    "_Aucun rapport de lecture trouvé sous `reports/` — lance "
    "`compare_pak_reader.py run --tool ...` d'abord._"
)
READ_TABLE_HEADER = (
    "| Outil | Mode | .pak | Erreurs | Index/extraction (s) | Contenu (s) | Total (s) |"
)
READ_TABLE_SEP = "|---|---|---:|---:|---:|---:|---:|"

READ_MODE_LABELS = {
    "python": ("bg3pythonpaklib", "natif == pipeline"),
    "rust-native": ("bg3rustpaklib", "natif"),
    "rust": ("bg3rustpaklib", "pipeline (PyO3)"),
    "divine": ("Divine.exe", "pipeline (Wine/Proton)"),
}

CREATE_EDIT_TABLE_EMPTY = (
    "_Aucun résultat création/édition trouvé — lance `pak_bench_cli.py create`/`edit` d'abord._"
)
CREATE_EDIT_TABLE_HEADER = (
    "| Outil | Scénario | Runs | Échecs | Médiane (s) | Min (s) | Max (s) | Round-trip OK |"
)
CREATE_EDIT_TABLE_SEP = "|---|---|---:|---:|---:|---:|---:|---:|"
CREATE_EDIT_PYTHONPAKLIB_NOTE = (
    "bg3pythonpaklib n'apparaît pas ci-dessus : lecture seule (cf. "
    "`.claude/TODO.md` §1f-1i), pas de scénario création/édition mesurable."
)

LIMITATION_NO_REAL_PAK = (
    "**Pas de mesure sur de vrais `.pak` du jeu dans cette passe** — "
    "uniquement des fixtures synthétiques générées par "
    "`scripts/pak_bench/synthetic.py` (décision explicite : voir le "
    "spec). Les chiffres ci-dessus valident le *pipeline de mesure*, "
    "pas la performance absolue attendue sur de vraies archives BG3."
)
LIMITATION_DIVINE_WINE = (
    "Divine.exe sous Linux passe par Wine/Proton — non représentatif "
    "du natif Windows (gap déjà documenté dans les README de "
    "bg3pythonpaklib/bg3rustpaklib)."
)

# -- report.py : graphes matplotlib -----------------------------------------

READ_CHART_MODE_LABELS = {
    "python": "bg3pythonpaklib\n(natif == pipeline)",
    "rust-native": "bg3rustpaklib\n(natif)",
    "rust": "bg3rustpaklib\n(pipeline PyO3)",
    "divine": "Divine.exe\n(pipeline Wine/Proton)",
}
READ_CHART_TITLE = "Lecture .pak — natif vs pipeline, par outil"
READ_CHART_YLABEL = "Secondes (total du lot)"
READ_CHART_SERIES_INDEX = "Index/extraction"
READ_CHART_SERIES_CONTENT = "Lecture contenu (échantillon)"

CREATE_EDIT_CHART_TITLE = "Création / édition .pak — médiane par outil x scénario"
CREATE_EDIT_CHART_YLABEL = "Médiane (s)"

# -- create_edit.py : messages d'erreur/aide --------------------------------

NATIVE_TIMING_MISSING = (
    "Binaire '{name}' introuvable ({path}) — compile-le d'abord :\n"
    "  cargo build --example native_timing --release "
    "--manifest-path Tools/bg3rustpaklib/Cargo.toml"
)
NATIVE_TIMING_NO_JSON = "pas de sortie JSON (code {code}) : {stderr}"
NATIVE_TIMING_BAD_JSON = "JSON invalide depuis native_timing : {exc}"

# -- pak_bench_cli.py : CLI ---------------------------------------------------

CLI_DESCRIPTION = """\
Point d'entrée CLI pour les scénarios création/édition (single + batch)
et la génération du rapport (Markdown + PNG) du benchmark .pak BG3. La
lecture (single + batch) reste sur son point d'entrée historique
`scripts/compare_pak_reader.py run --tool {python,rust,rust-native,divine}`
(rétro-compatible, cf. docs/superpowers/specs/
2026-09-15-pak-tools-benchmark-design.md).

Sous-commandes :
    create   — crée N .pak synthétiques depuis N dossiers source (bg3rustpaklib natif + Divine.exe)
    edit     — extrait + modifie un sous-ensemble + recrée N .pak (mêmes outils)
    fixtures — génère les dossiers source/overlay synthétiques utilisés par create/edit --synthetic
    report   — agrège reports/*.json (lecture + création/édition) en Markdown + PNG

Exemple bout-en-bout avec fixtures synthétiques (aucun vrai .pak requis) :

    python scripts/pak_bench_cli.py create --synthetic --count 3 --repeat 3
    python scripts/pak_bench_cli.py edit --synthetic --count 2 --repeat 3
    python scripts/pak_bench_cli.py report
"""

HELP_FIXTURES = "Génère des dossiers source synthétiques"
HELP_CREATE = "Scénario create (single + batch)"
HELP_EDIT = "Scénario edit (single + batch)"
HELP_SOURCE_DIRS = "Dossiers source réels (sinon --synthetic)"
HELP_SYNTHETIC = "Génère des fixtures synthétiques au lieu de dossiers réels"
HELP_COUNT_SYNTHETIC = "Nombre de fixtures synthétiques (avec --synthetic)"
HELP_REPEAT = "Nombre de runs (pour médiane/min/max)"
HELP_SKIP_DIVINE = "Ne pas mesurer Divine.exe (plus rapide, ex. sans Wine dispo)"
HELP_OVERLAY_FRACTION = "Fraction des fichiers modifiés par l'édition"
HELP_REPORT = "Génère le rapport Markdown + PNG à partir de reports/*.json"

MSG_NO_SOURCE_DIRS = (
    "Aucun dossier source (précise --synthetic --count N ou des dossiers en positionnels)."
)
MSG_DIVINE_SKIPPED = (
    "  [Divine.exe] ignoré (introuvable ou --skip-divine) — cf. --divine-exe/--reference-path."
)
MSG_REPORT_WRITTEN = "Rapport écrit : {path}"
MSG_MARKDOWN_WRITTEN = "Rapport Markdown écrit : {path}"
MSG_READ_CHART_WRITTEN = "Graphe lecture écrit : {path}"
MSG_READ_CHART_SKIPPED = (
    "Graphe lecture non généré (matplotlib absent ou aucun rapport de lecture)."
)
MSG_CE_CHART_WRITTEN = "Graphe création/édition écrit : {path}"
MSG_CE_CHART_SKIPPED = "Graphe création/édition non généré (matplotlib absent ou aucun résultat)."
