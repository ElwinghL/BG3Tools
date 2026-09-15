# Spec — Benchmark comparatif des outils .pak BG3 (Divine.exe / bg3pythonpaklib / bg3rustpaklib)

Date : 2026-09-15
Branche : `feat/PakToolsBenchmark`
Statut : implémenté (cette passe), voir "Limitations" en fin de doc.

## 1. Objectif

Comparer les trois outils qui manipulent les archives `.pak` (LSPK) de
BG3 — Divine.exe (LSLib, référence), bg3pythonpaklib (Python pur, lecture
seule) et bg3rustpaklib (Rust, lecture ET écriture) — sur les fonctions
communes, documenter les écarts fonctionnels non communs, produire des
visuels parlants (Markdown + PNG), et prévoir des scénarios sur pak
individuel, en batch, en création from scratch et en édition.

## 2. Décisions validées (contexte : conversation d'origine)

1. Étendre l'existant (`scripts/compare_pak_reader.py`, 796 lignes,
   harness de lecture déjà en place) plutôt que repartir de zéro.
2. Architecture : logique commune extraite vers `scripts/pak_bench/`
   (`common.py`), `compare_pak_reader.py` reste le point d'entrée CLI
   historique pour la lecture (rétro-compatible), nouveaux scénarios
   création/édition/batch/rapport dans `scripts/pak_bench_cli.py` +
   `scripts/pak_bench/{create_edit,report,synthetic}.py`.
3. Matrice de capacités (reproduite telle qu'approuvée, section 4).
4. Sortie : Markdown + PNG (matplotlib) versionnés dans le repo, sous
   `docs/pak-tools-benchmark/` (`reports/` est gitignored — les JSON
   bruts d'un run restent locaux/regénérables, seul le rapport de
   synthèse est versionné).

## 3. Changement de méthodologie (décisions ultérieures, cette même session)

Deux consignes complémentaires ont affiné le design initial après le début
de l'implémentation — elles priment sur toute description antérieure de ce
document ou d'un message précédent qui les contredirait :

### 3.a Pas de mesure sur de vrais `.pak` du jeu dans cette passe

Le harness n'a **pas** été exécuté contre les vrais `.pak` de l'installation
BG3 de la machine (ils existent — `.../Baldurs Gate 3/Data/*.pak`, 221
fichiers trouvés lors de l'exploration — mais leur usage a été explicitement
écarté par l'utilisateur pour cette passe). Toutes les mesures produites
ici utilisent des fixtures **synthétiques** générées par
`scripts/pak_bench/synthetic.py` (profils "small-many"/"large-few"/"mixed",
contenu pseudo-aléatoire seedé pour la reproductibilité). Elles valident le
*pipeline de mesure* (le harness tourne bout en bout, round-trip vérifié,
rapport généré) — pas la performance absolue attendue sur de vraies
archives BG3, qui reste à mesurer dans une passe ultérieure en pointant les
mêmes commandes vers un vrai dossier `Data/`.

### 3.b Mesurer chaque outil "dans son jus", séparément du coût pipeline réel

Un outil mesuré via un pont intermédiaire (FFI/PyO3, subprocess+Wine) ne
reflète pas sa performance réelle — cet overhead doit être visible et
séparé, jamais mélangé dans un seul chiffre :

- **bg3rustpaklib** : la perf "native" est mesurée par un binaire Rust
  autonome, sans Python/PyO3 dans la boucle —
  `Tools/bg3rustpaklib/examples/native_timing.rs`, compilé en `--release`
  (le crate a déjà `[profile.release]` avec `opt-level = 3`, `lto = "fat"`,
  `codegen-units = 1`). Ce binaire couvre maintenant lecture (mode legacy
  `--sample N <pak>`, contrat inchangé pour `compare_pak_reader.py
  --tool rust-native`) ET création/édition/batch (`create`, `edit`,
  `batch-create`, `batch-edit`). Le binding PyO3 (`rust/pak_reader_rs`)
  reste mesuré séparément (`--tool rust` dans `compare_pak_reader.py`)
  comme "coût pipeline" — mais seulement pour la *lecture* : le binding
  n'a jamais exposé l'écriture, et `bg3_mod_tui` n'utilise pas
  bg3rustpaklib en production aujourd'hui (confirmé : aucun import de
  `pak_reader_rs` dans `bg3_mod_tui/*.py`) — donc pour création/édition il
  n'existe tout simplement pas de chemin "pipeline" à mesurer pour cette
  lib ; une seule série "natif" est rapportée.
- **Divine.exe** : mesuré tel qu'invoqué réellement en production
  (`bg3_mod_tui/compat_framework.py`/`mod_fixer_fork.py`, Wine/Proton
  sous Linux) — c'est la série "pipeline". `create_edit.py` ajoute une
  mesure séparée de l'overhead de lancement pur (`divine_launch_overhead_
  seconds` : invocation triviale sans action valide, juste le coût
  Wine/CLR de démarrage) pour permettre d'annoter/soustraire cet overhead
  plutôt que le laisser polluer silencieusement les chiffres d'opération.
  Non représentatif du natif Windows (gap déjà documenté dans les README
  bg3pythonpaklib/bg3rustpaklib).
- **bg3pythonpaklib** : pur Python, in-process, appelé tel qu'utilisé
  réellement (`bg3_mod_tui.pak_reader`, `--tool python`) — natif ==
  pipeline, une seule série (pas de duplication trompeuse dans les
  graphes/tableaux).

Le rapport (`scripts/pak_bench/report.py`) reflète cette distinction :
table de lecture avec une colonne "Mode" (`natif == pipeline` /
`natif` / `pipeline (PyO3)` / `pipeline (Wine/Proton)`), et un graphe par
paire de séries plutôt qu'un chiffre unique par outil.

## 4. Matrice de capacités

| Capacité | Divinity.exe (LSLib) | bg3pythonpaklib | bg3rustpaklib |
|---|---|---|---|
| Lecture pak (index, extraction) | Oui | Oui | Oui |
| Lecture batch (N pak) | Oui (1 process/pak, coût de lancement Wine à chaque fois) | Oui (in-process, boucle) | Oui (in-process, boucle) |
| Création pak (from scratch) | Oui | Non (lecture seule) | Oui |
| Édition pak | Oui (extract → modifier → recreate, pas d'édition incrémentale native) | Non | Oui (même pattern extract/recreate) |
| Archives solides, API async, `.loca` | Partiel | Non | Oui |

Les cases "Non" ne sont pas mesurées en perf — juste actées comme écart
fonctionnel, avec pointeur vers `.claude/TODO.md` §1f-1i (bg3pythonpaklib
lecture seule, chantier séparé non fait).

## 5. Scénarios et métriques

Pour chaque scénario mesurable : plusieurs runs (`--repeat N`, défaut 3),
médiane/min/max, plus correctness (round-trip vérifié en rouvrant le `.pak`
produit et en comparant `verify_ok`/nombre de fichiers — comparaison
structurelle complète type `cmd_diff` de `compare_pak_reader.py` réservée à
la lecture, pas dupliquée ici pour rester dans le budget de cette passe).

| Scénario | Outils | Entrée point |
|---|---|---|
| Lecture single | python, rust (PyO3), rust-native, divine | `compare_pak_reader.py run --tool ...` |
| Lecture batch | python, rust, rust-native, divine (`--divine-mode batch`) | idem |
| Création single | bg3rustpaklib (natif), Divine.exe (pipeline) | `pak_bench_cli.py create` |
| Création batch | bg3rustpaklib (natif, 1 process pour N), Divine.exe (N process — pas d'action batch native côté LSLib pour create-package) | `pak_bench_cli.py create` (plusieurs sources) |
| Édition single | bg3rustpaklib (natif), Divine.exe (pipeline) — extract+modify+recreate pour les deux | `pak_bench_cli.py edit` |
| Édition batch | idem, en lot | `pak_bench_cli.py edit` (plusieurs sources) |

bg3pythonpaklib n'apparaît dans aucun scénario création/édition (lecture
seule).

## 6. Architecture des fichiers

```
scripts/
  compare_pak_reader.py     # CLI lecture (existant, rétro-compatible ; importe pak_bench.common)
  pak_bench_cli.py          # CLI création/édition/batch/rapport (nouveau)
  pak_bench/
    __init__.py
    common.py                # PakRecord, ScenarioResult, hashing, I/O rapport JSON, median (extrait de compare_pak_reader.py)
    create_edit.py            # scénarios bg3rustpaklib (native_timing) + Divine.exe (subprocess/Wine)
    synthetic.py               # génération de fixtures source/overlay synthétiques (pas de vrai .pak requis)
    report.py                  # agrégation JSON -> Markdown + PNG matplotlib

Tools/bg3rustpaklib/examples/
  native_timing.rs           # binaire release, lecture legacy + création/édition/batch, sans Python/PyO3

docs/pak-tools-benchmark/     # rapport versionné (Markdown + PNG), régénéré par `pak_bench_cli.py report`
tests/
  test_pak_bench.py           # tests de la logique pure (pas de subprocess/vrai outil)
```

`reports/` reste gitignored (sortie brute JSON d'un run local, régénérable)
— seul `docs/pak-tools-benchmark/*.md`/`*.png` est versionné, en pointant
`pak_bench_cli.py report --out-dir docs/pak-tools-benchmark`.

## 7. Limitations de cette passe (à lever dans un chantier suivant)

- Aucune mesure sur de vrais `.pak` BG3 (voir §3.a) — à refaire en
  pointant `compare_pak_reader.py --dir`/`pak_bench_cli.py create|edit`
  vers de vrais dossiers de mod et un vrai `Data/` de l'installation.
- L'overhead de lancement Divine.exe est mesuré séparément
  (`divine_launch_overhead_seconds`) mais pas encore soustrait
  automatiquement des chiffres "pipeline" dans le rapport agrégé — la
  fonction existe, l'intégration au rapport Markdown/PNG reste à faire.
- Pas d'Artifact HTML interactif publié dans cette passe (temps de la
  session insuffisant après les changements de méthodologie en cours de
  route) — le rapport Markdown+PNG versionné couvre l'exigence minimale ;
  publier un Artifact à partir de ces mêmes données JSON reste un suivi
  simple.
- `create-batch`/`edit-batch` côté Divine.exe ne sont pas de vrais modes
  batch amortis (LSLib n'a pas d'action native `create-packages` au
  pluriel comme il a `extract-packages`) — un process par dossier source,
  documenté comme tel plutôt que présenté comme équivalent.
