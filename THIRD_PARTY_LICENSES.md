# Licences tierces

Ce projet (ModTools / `bg3-mod-tui`, licence **MIT**, voir `LICENSE`)
s'appuie sur des dépendances Python/Rust et pilote des outils tiers pour
Baldur's Gate 3. Cette page recense leurs licences respectives, telles que
vérifiées sur leur dépôt/page d'origine (dates de vérification :
2026-09-10). ModTools ne redistribue le code d'aucun de ces outils dans ce
dépôt — les outils sous `Tools/` sont suivis comme des sous-modules git
séparés, chacun avec sa propre licence (voir `.gitmodules` et
`Tools/TOOLS.md`), pas vendorisés ici.

## 1. Dépendances Python (`pyproject.toml`)

| Paquet          | Licence         | Source vérifiée                                                                 |
| ---------------- | --------------- | -------------------------------------------------------------------------------- |
| `textual`         | MIT             | [PyPI](https://pypi.org/pypi/textual/json) (champ `license` + classifieur)       |
| `httpx`           | BSD-3-Clause    | [PyPI](https://pypi.org/pypi/httpx/json)                                         |
| `python-dotenv`   | BSD-3-Clause    | [PyPI](https://pypi.org/pypi/python-dotenv/json)                                 |
| `tomlkit`         | MIT             | [PyPI](https://pypi.org/pypi/tomlkit/json)                                       |
| `zstandard`       | BSD-3-Clause    | [GitHub indygreg/python-zstandard](https://github.com/indygreg/python-zstandard) (PyPI ne renseigne pas le champ `license`) |
| `lz4`             | BSD-3-Clause    | [GitHub python-lz4/python-lz4](https://github.com/python-lz4/python-lz4)         |
| `pytest` (dev)    | MIT             | [GitHub pytest-dev/pytest](https://github.com/pytest-dev/pytest)                 |

Toutes des licences permissives, compatibles avec un usage tel quel
(dépendances non modifiées, installées via pip/Poetry).

## 2. LSLib / Divine.exe

- **Projet** : [Norbyte/lslib](https://github.com/Norbyte/lslib) (outil de
  référence pour les formats de fichiers Larian — `.pak`/LSPK, LSF, etc.).
- **Licence** : **MIT** (confirmée via l'API GitHub du dépôt).
- **Usage dans ModTools** : `Tools/ExportTools/` (voir `Tools/TOOLS.md`) ;
  téléchargé par `bg3_mod_tui/tools_manager.py`, piloté en sous-processus
  (`Divine.exe`) par `bg3_mod_tui/compat_framework.py` et
  `bg3_mod_tui/pak_metadata.py` pour empaqueter/inspecter des `.pak`. Aucun
  code de LSLib n'est copié dans ce dépôt — seul le binaire est téléchargé
  et exécuté par l'utilisateur.

### Format LSPK/LSF — `bg3_mod_tui/pak_reader.py`

Ce module est un lecteur natif Python (sans `Divine.exe`) du format
d'archive `.pak` de Larian. Il ne contient aucun code copié de LSLib, mais
sa compréhension du format binaire (structure des headers, tailles des
champs, bitmask de compression) a été construite en lisant le code source
de référence de LSLib — le module le cite déjà explicitement dans son
docstring :

> Format LSPK — documenté par le code source de référence LSLib (voir
> https://github.com/Norbyte/lslib, `LSLib/LS/PackageFormat.cs` et
> `PackageReader.cs`), pas de spécification officielle Larian publiée.

Cette page consolide cette attribution : la lecture/compréhension du
format est due au travail de reverse engineering de **Norbyte** dans LSLib
(MIT), même si aucun code n'en est directement repris.

## 3. BG3 Script Extender (BG3SE)

- **Projet** : [Norbyte/bg3se](https://github.com/Norbyte/bg3se).
- **Licence** : **MIT avec « Commons Clause »** (fichier `LICENSE` du
  dépôt) — usage, modification et distribution libres, mais la clause
  Commons Clause interdit de **vendre** le logiciel ou un service dont la
  valeur dérive substantiellement de ses fonctionnalités.
- **Usage dans ModTools** : outil tiers listé dans `Tools/TOOLS.md`
  (`Tools/BG3 Script Extender/`), téléchargé/lancé via le menu « Lancer un
  outil... » — non modifié, non redistribué dans le dépôt git.

## 4. BG3 Mod Manager

- **Projet** : [laughingleader/bg3modmanager](https://github.com/laughingleader/bg3modmanager).
- **Licence** : **MIT** (confirmée via l'API GitHub du dépôt).
- **Usage** : outil tiers listé dans `Tools/TOOLS.md`, téléchargé/lancé tel
  quel.

## 5. BG3 Load Order Optimizer

- **Projet** : [Nemix3D/bg3-load-order-optimizer](https://github.com/Nemix3D/bg3-load-order-optimizer).
- **Licence** : **propriétaire, non open-source** — « BG3 Load Order
  Optimizer Personal Use License v1.0 » (fichier `LICENSE` du dépôt).
  Autorise le téléchargement et l'exécution d'une copie non modifiée à
  usage personnel non commercial ; interdit explicitement la
  redistribution, la modification et la création d'œuvres dérivées.
- **Usage dans ModTools** : outil tiers listé dans `Tools/TOOLS.md`,
  téléchargé/lancé tel quel, jamais modifié ni redistribué — usage
  conforme aux conditions de cette licence.

## 6. Para Tool

- **Projet** : [Paramonov86/Para_Tool](https://github.com/Paramonov86/Para_Tool).
- **Licence** : **non spécifiée** — aucun champ de licence détecté par
  l'API GitHub (`"license": null`), pas de fichier `LICENSE` identifié à
  la racine du dépôt au moment de la vérification. Usage tel quel
  (téléchargement/exécution du binaire officiel), sans modification ni
  redistribution.

## 7. Native Mod Loader

- **Projet** : [gottyduke/NativeModLoader](https://github.com/gottyduke/NativeModLoader)
  ([page Nexus Mods associée](https://www.nexusmods.com/baldursgate3/mods/944)).
- **Licence** : **MIT** (confirmée via l'API GitHub du dépôt principal).
- **Usage** : listé dans `Tools/TOOLS.md` ; contrairement aux autres
  outils, la DLL n'est pas récupérable automatiquement depuis GitHub par
  `tools_manager.py` (à télécharger manuellement par l'utilisateur depuis
  Nexus Mods ou une release GitHub).

## 8. BG3 Compatibility Framework

- **Projet** : [BG3-Community-Library-Team/BG3-Compatibility-Framework](https://github.com/BG3-Community-Library-Team/BG3-Compatibility-Framework).
- **Licence** : **MIT** (confirmée via l'API GitHub du dépôt).
- **Usage dans ModTools** : `bg3_mod_tui/compat_framework.py` télécharge
  les sources de ce mod (pas de `.pak` prêt à l'emploi disponible en
  release) et les compile localement via `Divine.exe` (LSLib) en un
  `CompatibilityFramework.pak`. Le `.pak` résultant n'est jamais commité
  dans ce dépôt (voir `.gitignore`) — seules les sources tierces,
  téléchargées à la demande, sont utilisées, sans modification.

## 9. Mod Fixer — repackaging propre ([ElwinghL/ModFixer](https://github.com/ElwinghL/ModFixer), MIT)

- **Technique d'origine** : [Mod Fixer sur Nexus Mods](https://www.nexusmods.com/baldursgate3/mods/141)
  (mod #141), par **[figs999](https://www.nexusmods.com/profile/figs999)**,
  qui crédite lui-même **Norbyte** ([BG3 Script Extender](https://github.com/Norbyte/bg3se))
  pour la technique sous-jacente (forcer la recompilation de la story
  Osiris via un fichier déposé dans `Story/RawFiles/Goals/` du module de
  base). Nexus Mods ne permet pas à un auteur de fixer une licence de
  projet ; la page d'origine n'en spécifie pas.
- **Ce que contient réellement le mod** : un unique fichier **vide**
  (`Mods/Gustav/Story/RawFiles/Goals/ForceRecompile.txt`), sans `meta.lsx`
  propre — aucun contenu créatif/code à reprendre. `ElwinghL/ModFixer` est
  donc un repackaging écrit de zéro (nouveau `meta.lsx`, UUID généré),
  reproduisant seulement ce même fichier vide au même chemin — pas une
  copie des fichiers de l'auteur d'origine.
- **Licence** : **MIT** ([LICENSE](https://github.com/ElwinghL/ModFixer/blob/main/LICENSE))
  pour ce repackaging (`meta.lsx` + empaquetage, écrits dans ce dépôt) —
  ne couvre pas et ne peut pas couvrir la *technique* elle-même, créditée
  ci-dessus à figs999 et Norbyte.
- **Usage dans ModTools** : sous-module git `Tools/ModFixer/` (voir
  `Tools/TOOLS.md`). `bg3_mod_tui/mod_fixer_fork.py` construit ce module
  directement depuis ce sous-module, en remplacement du `ModFixer.pak`
  déjà déployé par l'utilisateur (sauvegardé en `ModFixer.pak.orig`, pour
  rester réversible) — ne dépend plus d'extraire le `.pak` de l'utilisateur
  pour en tirer le contenu.

## 10. MoreReactiveCompanions — non applicable

Retiré de cette page : ModTools appelle directement l'application de
configuration fournie par le mod (téléchargée depuis Nexus Mods, jamais
modifiée ni redistribuée) — aucune obligation de licence n'est déclenchée
par ce simple lancement tel quel. Voir `Tools/TOOLS.md` pour le lien Nexus
d'origine si besoin.

## 11. bg3rustpaklib / bg3pythonpaklib / dépendances Rust (`rust/pak_reader_rs`)

- **bg3rustpaklib** ([ElwinghL/bg3rustpaklib](https://github.com/ElwinghL/bg3rustpaklib)) et **bg3pythonpaklib**
  ([ElwinghL/bg3pythonpaklib](https://github.com/ElwinghL/bg3pythonpaklib)) sont deux projets sœurs de ModTools
  (lecteurs LSPK natifs, Rust et Python), tous deux sous **licence MIT** — cohérente avec ce dépôt. Suivis
  comme sous-modules git sous `Tools/` (voir `Tools/TOOLS.md`) ; `bg3rustpaklib` est aussi une dépendance
  Cargo directe de `rust/pak_reader_rs` (crate de comparaison, voir `scripts/compare_pak_reader.py`).
- Dépendances Cargo de `rust/pak_reader_rs` (`cargo metadata`, vérifié le 2026-09-11) : `pyo3` (**MIT OR
  Apache-2.0**), `roxmltree` (**MIT OR Apache-2.0**), `regex` (**MIT OR Apache-2.0**), `flate2` (**MIT OR
  Apache-2.0**). Toutes permissives et compatibles avec la licence MIT de ce dépôt.

## 12. NMCM (Native Mod Configuration Menu)

- **Projet** : [Luiznunes12/bg3-nmcm](https://github.com/Luiznunes12/bg3-nmcm)
  (aussi disponible sur [mod.io](https://mod.io/g/baldursgate3/m/native-mod-configuration-menu)).
- **Licence** : **MIT** (confirmée via l'API GitHub du dépôt, vérifié le
  2026-09-13).
- **Usage dans ModTools** : outil tiers listé dans `Tools/TOOLS.md`
  (`Tools/bg3-nmcm/`), suivi comme les autres dépôts GitHub de ce fichier
  (sous-module git, voir `.gitmodules`) — non modifié, non redistribué
  dans ce dépôt.

## Résumé

| Outil/dépendance            | Licence                              | Statut de vérification |
| ---------------------------- | ------------------------------------- | ------------------------- |
| textual, httpx, python-dotenv, tomlkit, zstandard, lz4, pytest | MIT / BSD-3-Clause (voir §1) | Vérifié (PyPI/GitHub) |
| LSLib (Norbyte)               | MIT                                   | Vérifié (API GitHub)      |
| BG3SE (Norbyte)               | MIT + Commons Clause (pas de revente) | Vérifié (fichier LICENSE) |
| BG3 Mod Manager (laughingleader) | MIT                                | Vérifié (API GitHub)      |
| BG3 Load Order Optimizer (Nemix3D) | Propriétaire, usage personnel non modifiable | Vérifié (fichier LICENSE) |
| Para Tool (Paramonov86)       | Non spécifiée                         | Vérifié (absence de licence détectée) |
| Native Mod Loader (gottyduke) | MIT                                   | Vérifié (API GitHub)      |
| BG3 Compatibility Framework    | MIT                                   | Vérifié (API GitHub)      |
| Mod Fixer (ElwinghL/ModFixer, repackaging) | MIT | Vérifié (fichier LICENSE du dépôt) |
| bg3rustpaklib / bg3pythonpaklib (ElwinghL) | MIT | Vérifié (fichier LICENSE de chaque dépôt) |
| pyo3, roxmltree, regex, flate2 (Cargo, `rust/pak_reader_rs`) | MIT OR Apache-2.0 | Vérifié (`cargo metadata`) |

Aucun code source tiers n'est copié verbatim dans ce dépôt git : les
outils listés ci-dessus sont soit des dépendances Python installées via
pip/Poetry (non modifiées), soit des outils/mods tiers téléchargés à la
demande sous `Tools/` (ignorés par git, voir `.gitignore`) et exécutés en
sous-processus, à l'exception du format `.pak` (LSPK) dont la
compréhension, documentée dans `bg3_mod_tui/pak_reader.py`, s'appuie sur
le code source public de LSLib (Norbyte, MIT) sans en reprendre le code.
