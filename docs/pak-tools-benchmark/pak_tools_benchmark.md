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
| bg3pythonpaklib | natif == pipeline | 1 | 0 | 0.000 | 0.000 | 0.000 |
| bg3rustpaklib | natif | 1 | 0 | 0.000 | 0.000 | 0.000 |

## Création / édition (single + batch)

| Outil | Scénario | Runs | Échecs | Médiane (s) | Min (s) | Max (s) | Round-trip OK |
|---|---|---:|---:|---:|---:|---:|---:|
| bg3rustpaklib | create-batch | 8 | 0 | 0.0102 | 0.0049 | 0.0139 | 100% |
| bg3rustpaklib | create-single | 8 | 0 | 0.0108 | 0.0047 | 0.0232 | 100% |
| bg3rustpaklib | edit-batch | 8 | 0 | 0.0120 | 0.0089 | 0.0150 | 100% |
| bg3rustpaklib | edit-single | 8 | 0 | 0.0124 | 0.0090 | 0.0166 | 100% |

bg3pythonpaklib n'apparaît pas ci-dessus : lecture seule (cf. `.claude/TODO.md` §1f-1i), pas de scénario création/édition mesurable.

## Limitations de cette passe

- **Pas de mesure sur de vrais `.pak` du jeu dans cette passe** — uniquement des fixtures synthétiques générées par `scripts/pak_bench/synthetic.py` (décision explicite : voir le spec). Les chiffres ci-dessus valident le *pipeline de mesure*, pas la performance absolue attendue sur de vraies archives BG3.
- Divine.exe sous Linux passe par Wine/Proton — non représentatif du natif Windows (gap déjà documenté dans les README de bg3pythonpaklib/bg3rustpaklib).

