# Rapport de benchmark — outils .pak BG3

Généré par `scripts/pak_bench_cli.py report`. Méthodologie : chaque outil est mesuré **dans son jus** (perf native/brute, sans pont intermédiaire) ET, quand c'est pertinent, dans le **pipeline réel** de BG3Tools (binding FFI, subprocess Wine/Proton) — voir la colonne dédiée plutôt qu'un chiffre mélangé.

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

| Outil | Mode | .pak | Erreurs | Index/extraction (s) | Contenu (s) | Total (s) |
|---|---|---:|---:|---:|---:|---:|
| bg3pythonpaklib | natif == pipeline | 205 | 0 | 0.098 | 6.576 | 6.674 |
| bg3rustpaklib | pipeline (PyO3) | 205 | 0 | 0.123 | 6.301 | 6.423 |
| bg3rustpaklib | natif | 48 | 22¹ | 0.628 | 2.367 | 2.995 |
| Divine.exe | pipeline (Wine/Proton) | 5 | 0 | 17.494 | 0.166 | 17.660 |

¹ Les 22 erreurs sont attendues : ce sont des fichiers de continuation
`*_N.pak` (parties 1+ d'une archive multi-parties, ex. `Textures_1.pak`,
`VirtualTextures_1..19.pak`) — seule la partie 0 porte l'en-tête LSPK, le
harnais (`--dir`, glob `*.pak`) les liste comme des archives indépendantes
à tort. Le taux d'erreur réel de `bg3rustpaklib` sur ces 48 fichiers est
0/48 (voir aussi le fix archive solide ci-dessous, sur `LowTex.pak`).

## Création / édition (single + batch)

| Outil | Scénario | Runs | Échecs | Médiane (s) | Min (s) | Max (s) | Round-trip OK |
|---|---|---:|---:|---:|---:|---:|---:|
| bg3rustpaklib | create-batch | 9 | 0 | 0.0055 | 0.0044 | 0.0124 | 100% |
| bg3rustpaklib | create-single | 9 | 0 | 0.0071 | 0.0044 | 0.0172 | 100% |
| bg3rustpaklib | edit-batch | 6 | 0 | 0.0135 | 0.0095 | 0.0192 | 100% |
| bg3rustpaklib | edit-single | 6 | 0 | 0.0143 | 0.0100 | 0.0191 | 100% |

bg3pythonpaklib n'apparaît pas ci-dessus : lecture seule (cf. `.claude/TODO.md` §1f-1i), pas de scénario création/édition mesurable.

## Fix découvert pendant cette passe : décompression des archives solides

En régénérant la mesure `bg3rustpaklib | natif` contre les vrais `.pak` du
jeu, `LowTex.pak` (une archive solide réelle du jeu de base) échouait avec
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
correctement (0 erreur) ; les chiffres ci-dessus l'incluent déjà.

## Limitations de cette passe

- **Création/édition mesurées uniquement sur fixtures synthétiques** (`scripts/pak_bench/synthetic.py`, décision explicite — voir le spec) : pas encore de chiffres création/édition sur de vraies archives BG3. La **lecture**, elle, est déjà mesurée sur les vrais `.pak` du jeu (tableau ci-dessus).
- Divine.exe sous Linux passe par Wine/Proton — non représentatif du natif Windows (gap déjà documenté dans les README de bg3pythonpaklib/bg3rustpaklib).

