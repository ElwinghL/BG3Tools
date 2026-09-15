# Rapport de benchmark — outils .pak BG3

Généré par `scripts/pak_bench_cli.py report`. Méthodologie : chaque outil est mesuré **dans son jus** (perf native/brute, sans pont intermédiaire) ET, quand c'est pertinent, dans le **pipeline réel** de BG3Tools (binding FFI, subprocess Wine/Proton) — voir la colonne dédiée plutôt qu'un chiffre mélangé.

**Dashboard interactif** (matrice de capacités, graphes lecture natif/pipeline et création/édition, tableau filtrable des 253 `.pak` réels mesurés, highlight du cas `LowTex.pak`) : <https://claude.ai/artifact/Wk9Gtx6m4uiSJpWGvAjJoZ> — données consolidées par `scripts/pak_bench/export_dashboard_data.py` depuis `reports/*.json`.

## Matrice de capacités

| Capacité | Divinity.exe (LSLib) | bg3pythonpaklib | bg3rustpaklib |
|---|---|---|---|
| Lecture pak (index, extraction) | Oui | Oui | Oui |
| Lecture batch (N pak) | Oui (1 process/pak, coût Wine/pak) | Oui (in-process) | Oui (in-process) |
| Création pak (from scratch) | Oui | Non (lecture seule) | Oui |
| Édition pak | Oui (extract/modifier/recreate) | Non | Oui (idem) |
| Archives solides, API async, .loca | Partiel | Non | Oui |

Les cases "Non" ne sont pas mesurées en perf — juste actées comme écart
fonctionnel, avec pointeur vers `.claude/TODO.md` §1f-1i.

## Lecture (single + batch)

253 vrais `.pak` du jeu : 48 du jeu de base (`Data/`) + 205 de mods actifs
(`Mods/`). Aucune fixture synthétique en lecture.

| Outil | Mode | .pak | Erreurs | Index/extraction (s) | Contenu (s) | Total (s) |
|---|---|---:|---:|---:|---:|---:|
| bg3pythonpaklib | natif == pipeline | 253 | 22¹ | 2.105 | 13.007 | 15.112 |
| bg3rustpaklib | pipeline (PyO3) | 253 | 23¹ ² | 0.676 | 16.702 | 17.378 |
| bg3rustpaklib | natif | 253 | 22¹ | 0.695 | 6.608 | 7.302 |
| Divine.exe | pipeline (Wine/Proton) | 48³ | 6⁴ | 309.787 | 3.135 | 312.922 |

¹ Les 22 erreurs communes sont attendues : ce sont des fichiers de
continuation `*_N.pak` (parties 1+ d'une archive multi-parties, ex.
`Textures_1.pak`, `VirtualTextures_1..19.pak`) — seule la partie 0 porte
l'en-tête LSPK, le harnais (`--dir`, glob `*.pak`) les liste comme des
archives indépendantes à tort. Le taux d'erreur réel sur ces fichiers est
0/253.

² bg3rustpaklib en pipeline PyO3 a une 23e erreur que les deux autres
n'ont pas : `LowTex.pak` (archive solide réelle du jeu de base). Le
binding PyO3 (`pak_reader_rs`) dépend de `bg3rustpaklib = "0.1"` publié
sur crates.io, qui contient encore le bug de décompression d'archive
solide trouvé et corrigé aujourd'hui (voir section ci-dessous) — le
fix n'est pas encore republié. Le mode `natif` (qui utilise le code
source local déjà patché) n'a pas cette erreur : `LowTex.pak` y réussit.

³ Divine.exe n'a été exercé que sur le jeu de base (48 fichiers) : le
mode per-file (un lancement Wine par `.pak`) a pris ~15 min pour 48
fichiers, donc un run sur les 205 mods en plus n'a pas été fait cette
passe. Le mode batch natif de Divine.exe/LSLib (un seul lancement Wine
pour tout un dossier) est cassé en amont — voir Limitations.

⁴ 6 échecs réels sur 48 : 3 timeouts (`Materials.pak`, `Models.pak`,
`SharedSounds.pak`) et 3 crashs sans message exploitable au-delà du bruit
de démarrage Wine (`Gustav.pak`, `Textures.pak`, `VirtualTextures.pak`),
probablement un épuisement mémoire sur les plus gros fichiers/archives
multi-parties. À l'inverse, Divine.exe réussit sur les parties de
continuation (`Textures_1.pak`, `VirtualTextures_1..19.pak`) prises
individuellement, contrairement aux deux lecteurs natifs — LSLib les
résout autrement (pas creusé plus loin).

## Création / édition (single + batch)

Sources réelles : contenu extrait de trois vrais `.pak` du jeu de base
(`GamePlatform.pak`, 43 fichiers/468 Ko ; `PsoCache.pak`, 1 fichier/3,1 Mo ;
`LowTex.pak`, 5991 fichiers/64 Mo décompressés — la même archive solide
que le fix ci-dessous), pas des fixtures synthétiques.

| Outil | Scénario | Runs | Échecs | Médiane (s) | Min (s) | Max (s) | Round-trip OK |
|---|---|---:|---:|---:|---:|---:|---:|
| bg3rustpaklib | create-batch | 9 | 0 | 0.0055 | 0.0022 | 0.4076 | 100% |
| bg3rustpaklib | create-single | 9 | 0 | 0.0064 | 0.0023 | 0.4201 | 100% |
| bg3rustpaklib | edit-batch | 9 | 0 | 0.0172 | 0.0049 | 0.4573 | 100% |
| bg3rustpaklib | edit-single | 9 | 0 | 0.0195 | 0.0046 | 0.4975 | 100% |

Le min correspond à `GamePlatform` (43 petits fichiers), le max à
`LowTex` (5991 fichiers, 64 Mo) — l'écart illustre le passage à l'échelle
plutôt qu'une instabilité de mesure. Divine.exe non exercé sur ces
scénarios (`--skip-divine`) ; le code d'invocation existe et suit le
pattern déjà en prod, mais reste non testé en exécution création/édition.

bg3pythonpaklib n'apparaît pas ci-dessus : lecture seule (cf. `.claude/TODO.md` §1f-1i), pas de scénario création/édition mesurable.

## Fix découvert pendant cette passe : décompression des archives solides

En mesurant `bg3rustpaklib | natif` contre les vrais `.pak` du jeu,
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
correctement en mode natif (0 erreur) ; le pipeline PyO3 (crates.io)
n'a pas encore ce fix, cf. note ² ci-dessus.

## Bug Divine.exe/LSLib trouvé au passage (mode batch)

Le mode batch natif de Divine.exe (action `extract-packages`, un seul
lancement Wine pour tout un dossier — bien plus rapide que per-file)
plante systématiquement : `CommandLineActions.SetUpAndValidate` appelle
inconditionnellement `CommandLineArguments.GetResourceFormatByString`
sur `--input-format`, qui ne reconnaît que `lsb`/`lsf`/`lsj`/`lsx` — pas
`pak`, pourtant une valeur documentée comme valide pour `-i` en mode
batch. Résultat : `Fatal error. Internal CLR error. (0x80131506)`. Bug
upstream dans le binaire tiers pré-compilé
(`Tools/ExportTools/dist/Tools/Divine.exe`), pas corrigeable côté
script sans recompiler LSLib. Un vrai bug de syntaxe a aussi été trouvé
et corrigé au passage dans notre propre harnais (`-u` →
`--use-package-name`, le flag correct n'a pas de forme courte) — mais
ne suffit pas à rendre le mode batch utilisable.

## Limitations de cette passe

- **Divine.exe limité au jeu de base (48/253 `.pak`)** — le mode per-file est trop lent pour les 205 mods (~15 min pour 48 fichiers), le mode batch est cassé en amont (voir ci-dessus).
- **Divine.exe non exercé sur création/édition** (`--skip-divine` lors de ces runs) — le code d'invocation existe et suit le pattern déjà en prod, mais reste non testé en exécution sur ces scénarios.
- Divine.exe sous Linux passe par Wine/Proton pour la lecture — non représentatif du natif Windows (gap déjà documenté dans les README de bg3pythonpaklib/bg3rustpaklib).
