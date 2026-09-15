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
SECTION_SOLID_ARCHIVE_FIX = "## Fix découvert : décompression des archives solides"
SECTION_DIVINE_BATCH_BUG = "## Bug Divine.exe/LSLib trouvé au passage (mode batch)"
SECTION_LIMITATIONS = "## Limitations de cette passe"

DASHBOARD_LINK_LINE = (
    "**Dashboard interactif** (matrice de capacités, graphes lecture "
    "natif/pipeline et création/édition, tableau filtrable des `.pak` "
    "réels mesurés, highlight du cas `LowTex.pak`) : "
    "[`dashboard.html`](./dashboard.html) (fichier local autonome, à "
    "ouvrir directement dans un navigateur) — données consolidées par "
    "`scripts/pak_bench/export_dashboard_data.py` depuis `reports/*.json` "
    "(régénérable avec `pak_bench_cli.py report --update-dashboard`)."
)

READ_FOOTNOTE_CONTINUATION_FILES = (
    "¹ Les {n} erreurs communes à bg3pythonpaklib et bg3rustpaklib (natif "
    "comme pipeline) sont attendues : ce sont des fichiers de continuation "
    "`*_N.pak` (parties 1+ d'une archive multi-parties, ex. "
    "`Textures_1.pak`, `VirtualTextures_1..19.pak`) — seule la partie 0 "
    "porte l'en-tête LSPK, le harnais (`--dir`, glob `*.pak`) les liste "
    "comme des archives indépendantes à tort. Le taux d'erreur réel sur "
    "ces fichiers est 0."
)
READ_FOOTNOTE_LOWTEX_PIPELINE = (
    "² bg3rustpaklib en pipeline PyO3 a {n_extra} erreur(s) de plus que le "
    "mode natif sur le même lot : `LowTex.pak` (archive solide réelle du "
    "jeu de base). Le binding PyO3 (`pak_reader_rs`) dépend de "
    '`bg3rustpaklib = "0.1"` publié sur crates.io, qui contient encore le '
    "bug de décompression d'archive solide corrigé localement (voir "
    "section ci-dessous) — le fix n'est pas encore republié. Le mode "
    "`natif` (code source local déjà patché) n'a pas cette erreur."
)
READ_FOOTNOTE_DIVINE_SCOPE = (
    "³ Divine.exe n'a été exercé que sur {pak_count} `.pak` (les autres "
    "outils en couvrent {other_count}) : le mode per-file (un lancement "
    "Wine par `.pak`) est trop lent à grande échelle, et le mode batch "
    "natif de Divine.exe/LSLib (un seul lancement Wine pour tout un "
    "dossier) est cassé en amont — voir la section dédiée ci-dessous."
)
READ_FOOTNOTE_DIVINE_ERRORS = (
    "⁴ {n_errors} échec(s) réel(s) sur {pak_count} chez Divine.exe : "
    "typiquement des timeouts et des crashs sans message exploitable "
    "au-delà du bruit de démarrage Wine sur les plus gros fichiers/"
    "archives multi-parties (probable épuisement mémoire)."
)

SOLID_ARCHIVE_FIX_BODY = """\
En mesurant bg3rustpaklib en mode natif contre les vrais `.pak` du jeu,
`LowTex.pak` (une archive solide réelle du jeu de base) échouait avec
`Invalid LZ4 block size: 2147549184 > ...`. Root-cause et fix (voir le
commit correspondant dans `Tools/bg3rustpaklib`) :

1. `decompress_solid_archive()` découpait le frame LZ4 7 octets trop tard
   (le magic number LZ4 était donc absent de la tranche passée au
   décodeur, qui retombait sur un chemin heuristique produisant des
   tailles de bloc aberrantes).
2. Les offsets décompressés cumulés étaient assignés dans l'ordre de la
   table de fichiers plutôt que dans l'ordre de packing physique
   (`entry.offset` croissant).
3. `PackagedFile::size()` retombait sur `size_on_disk` pour toute entrée
   non individuellement compressée — correct pour une entrée classique
   (repli connu, cf. le bug `UncompressedSize=0` déjà documenté côté
   Python), mais faux pour une entrée d'archive solide, où ce repli n'a
   pas de sens.

Régression ajoutée : `test_lowtex_solid_archive_decompresses` (fixture
réelle locale, gitignored). `LowTex.pak` décompresse maintenant
correctement en mode natif (0 erreur) ; le pipeline PyO3 (crates.io) n'a
pas encore ce fix, cf. note ² ci-dessus.
"""

DIVINE_BATCH_BUG_BODY = """\
Le mode batch natif de Divine.exe (action `extract-packages`, un seul
lancement Wine pour tout un dossier — bien plus rapide que per-file)
plante systématiquement : `CommandLineActions.SetUpAndValidate` appelle
inconditionnellement `CommandLineArguments.GetResourceFormatByString` sur
`--input-format`, qui ne reconnaît que `lsb`/`lsf`/`lsj`/`lsx` — pas
`pak`, pourtant une valeur documentée comme valide pour `-i` en mode
batch. Résultat : `Fatal error. Internal CLR error. (0x80131506)`. Bug
upstream dans le binaire tiers pré-compilé
(`Tools/ExportTools/dist/Tools/Divine.exe`), pas corrigeable côté script
sans recompiler LSLib. Un vrai bug de syntaxe a aussi été trouvé et
corrigé au passage dans notre propre harnais (`-u` →
`--use-package-name`, le flag correct n'a pas de forme courte) — mais ne
suffit pas à rendre le mode batch utilisable.
"""

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

LIMITATION_CREATE_EDIT_DIVINE_SKIPPED = (
    "Divine.exe non exercé sur les scénarios création/édition "
    "(`--skip-divine` lors de ces runs) — le code d'invocation existe et "
    "suit le pattern déjà en prod, mais reste non testé en exécution sur "
    "ces scénarios."
)
LIMITATION_DIVINE_SCOPE_TEMPLATE = (
    "**Divine.exe limité en lecture à {pak_count}/{other_count} `.pak`** "
    "— le mode per-file est trop lent à grande échelle, le mode batch est "
    "cassé en amont (voir section dédiée ci-dessus)."
)
LIMITATION_DIVINE_WINE = (
    "Divine.exe sous Linux passe par Wine/Proton pour la lecture — non "
    "représentatif du natif Windows (gap déjà documenté dans les README "
    "de bg3pythonpaklib/bg3rustpaklib)."
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
HELP_UPDATE_DASHBOARD = (
    "Copie aussi le rapport/PNG vers docs/pak-tools-benchmark/ et réinjecte "
    "les données à jour dans dashboard.html (si présent)."
)

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
MSG_DASHBOARD_MD_COPIED = "Rapport copié vers {path}"
MSG_DASHBOARD_HTML_UPDATED = "Dashboard HTML mis à jour : {path}"
MSG_DASHBOARD_HTML_MISSING = (
    "{path} introuvable — dashboard jamais publié en local, données "
    "consolidées écrites dans reports/dashboard_data.json seulement."
)
