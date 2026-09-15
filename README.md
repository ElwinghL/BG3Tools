# BG3 Mod TUI — v1.0.0

[![CI](https://git.clementleboeuf.ovh:30009/elwinghit/BG3Tools/actions/workflows/ci.yml/badge.svg?branch=main)](https://git.clementleboeuf.ovh:30009/elwinghit/BG3Tools/actions?workflow=ci.yml)
[![Couverture](https://img.shields.io/badge/couverture-%E2%89%A575%25-brightgreen)](.gitea/workflows/ci.yml)
[![Licence](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

<!-- Le badge de couverture indique le seuil imposé par la CI
(`fail_under = 75` dans pyproject.toml), pas le pourcentage exact du
dernier run -- pas de service externe type Codecov branché pour l'instant
(voir .claude/TODO.md pour cette piste en tant que suite possible). -->

TUI (interface terminal) pour gérer l'installation de mods Baldur's Gate 3 :
téléchargement (Nexus Mods / mod.io), extraction vers le dossier `Mods/`
géré par le jeu, synchronisation de `modsettings.lsx`, et lancement des
outils tiers embarqués sous `Tools/` (BG3 Mod Manager, Script Extender,
Load Order Optimizer, ExportTools/LSLib, Para Tool, Native Mod Loader —
voir [Tools/TOOLS.md](Tools/TOOLS.md)).

Windows et Linux (Proton) sont supportés ; sous Linux, le lancement des
outils `.exe` est restreint au préfixe Proton de BG3 pour garantir un
environnement cohérent avec le jeu.

## Lancer l'application

- Linux/macOS : `./run.sh`
- Windows : `run.bat`

Ces scripts créent un environnement virtuel local (`.venv`), installent les
dépendances, puis démarrent le TUI. Au premier lancement, un assistant de
configuration demande l'emplacement d'installation de BG3 et met en place
les liens nécessaires (symlink `Mods/`, hardlink `modsettings.lsx`).

Au démarrage, le TUI essaie de se relancer automatiquement dans un
terminal dédié configuré avec la police MesloLGS NF (voir "Prérequis")
plutôt que de rester dans le terminal déjà ouvert par l'utilisateur — le
process d'origine se termine alors, remplacé par celui du nouveau
terminal. Sous Linux : Konsole (avec un profil créé/mis à jour
automatiquement), puis en repli kitty/alacritty/xterm/wezterm/
gnome-terminal/xfce4-terminal/terminator selon ce qui est installé. Sous
Windows : Windows Terminal (profil dédié créé dans son `settings.json`),
puis en repli PowerShell. Si rien de tout ça n'est disponible (pas
d'affichage graphique, aucun émulateur trouvé), le TUI démarre
simplement dans le terminal actuel. Désactivable avec
`BG3_MODTUI_NO_RELAUNCH=1` (utile si le terminal actuel est déjà
correctement configuré).

Une clé API Nexus Mods (`NEXUS_API_KEY`) et/ou mod.io (`MODIO_API_KEY`,
`MOD_IO_USER_ID`) sont nécessaires pour le téléchargement — voir
`.env.example`.

## Installation en package Python indépendant (hors du dépôt)

`bg3_mod_tui/` est aussi installable comme un package Python standard
(wheel), utilisable dans un venv séparé, sans le reste du dépôt BG3Tools à
côté — utile par exemple pour l'installer via `pipx`/`uv tool`, ou dans un
environnement dédié plutôt que via `run.sh`/`run.bat`.

```bash
# Depuis une copie du dépôt (ou un tarball/wheel publié) :
pip install .
# ou, pour obtenir juste le fichier .whl (ex: à copier/distribuer ailleurs) :
pip wheel . -w dist/
```

Ça installe la commande `bg3-mod-tui`, qui lance directement le TUI :

```bash
bg3-mod-tui
```

**Mode dépôt vs mode package installé.** L'usage principal reste de
lancer le TUI *depuis l'intérieur du dépôt* (`./run.sh`/`run.bat`) : dans
ce cas, `bg3modtools.toml`, `.env`, `BG3_Managed/` et `Tools/` restent à la
racine du dépôt, comme avant. Si le package est installé et exécuté *en
dehors* du dépôt (aucun `.git` ni dossier `Tools/` à côté du code source
installé), il bascule automatiquement vers un dossier de configuration XDG
dédié :

- `$XDG_CONFIG_HOME/bg3-mod-tui/` si `XDG_CONFIG_HOME` est défini ;
- sinon `~/.config/bg3-mod-tui/`.

`bg3modtools.toml`, `.env` et `BG3_Managed/` (mods gérés, profils, logs,
etc.) sont alors créés sous ce dossier au lieu de la racine du dépôt. Les
fichiers spécifiques au dépôt (`Tools/` avec les outils tiers embarqués,
`nexus_links_to_add.md`, `Tools/TOOLS.md`) n'existent pas dans ce mode :
les fonctionnalités qui en dépendent (téléchargement/lancement des outils
tiers listés dans `Tools/TOOLS.md`, import du fichier de liens Nexus) se
comportent alors en best-effort (dossier/fichier absent signalé, sans
bloquer le reste du TUI) plutôt que d'empêcher le lancement ; le mode
"dépôt" reste donc recommandé pour profiter de l'intégralité des
fonctionnalités. Voir `bg3_mod_tui/config.py` (`resolve_project_root`).

## Fonctionnalités (menu principal)

1. **Télécharger les mods (Nexus)** — lit `nexus_links_to_add.md` (un lien
   ou ID de mod par ligne), télécharge la dernière version de chaque
   variante disponible (MAIN/UPDATE/OPTIONAL) vers les archives gérées.
2. **Récupérer les mods (mod.io)** — télécharge les mods auxquels le
   compte mod.io configuré est abonné.
3. **Nettoyer les .pak de Mods/** — retire les `.pak` du dossier géré.
4. **Synchroniser modsettings.lsx** — recale le fichier d'ordre de charge
   du profil sur les mods réellement présents.
5. **Extraire les archives vers Mods/** — décompresse les archives
   téléchargées (`Tools/Archives_installees/_a_traiter/`) et copie leurs
   `.pak` vers `Mods/`.
6. **Télécharger/MAJ les outils** — récupère/actualise les outils listés
   dans `Tools/TOOLS.md`.
7. **Lancer un outil...** — sélectionne et lance un exécutable trouvé
   sous `Tools/` (via le préfixe Proton de BG3 sous Linux).
8. **Ouvrir protontricks** (Linux uniquement) — ouvre l'interface
   winetricks sur le préfixe Proton de BG3.

## Structure du dépôt

- `bg3_mod_tui/` — code source du TUI (Python, [Textual](https://textual.textualize.io/)).
- `Tools/` — outils tiers (binaires ignorés par git, voir `.gitignore` et
  `Tools/TOOLS.md` pour leur origine).
- `nexus_links_to_add.md` — liste de travail perso (liens/IDs Nexus à
  traiter) ; suivi par git comme gabarit vide, contenu réel local
  uniquement (`git update-index --skip-worktree`).
- `THIRD_PARTY_LICENSES.md` — licences des dépendances Python et des
  outils/mods tiers utilisés par ModTools.

## Développement

Installation des dépendances via [uv](https://docs.astral.sh/uv/) :

```bash
uv sync
uv run bg3-mod-tui
```

`pip install -e .` (utilisé par `run.sh`/`run.bat`) fonctionne aussi
directement, `pyproject.toml` étant lu par les deux (backend `hatchling`,
métadonnées au format standard PEP 621).

### Créer une release

```bash
./scripts/make_release.sh
```

Empaquette `bg3_mod_tui/`, les scripts de lancement et la doc dans
`dist/bg3-mod-tui-vX.Y.Z.zip` (version lue dans `pyproject.toml`), et pose
le tag git `vX.Y.Z` correspondant (à pousser ensuite avec
`git push origin vX.Y.Z`).

### Release automatique (Gitea Actions)

`.gitea/workflows/release.yml` déclenche ce même script automatiquement à
chaque push sur `main` qui modifie `pyproject.toml` (donc quand la version
est bumpée) : il pose le tag, le pousse, puis publie une Release Gitea avec
le zip en pièce jointe. Rien ne se passe si le tag existe déjà (version
inchangée). Nécessite un runner Gitea Actions enregistré sur l'instance.

## Prérequis

- Python ≥ 3.11
- Sous Linux : `protontricks` (menu "Ouvrir protontricks") pour les
  réglages Wine du préfixe BG3.
- **Police MesloLGS NF** (Regular/Bold/Italic/Bold Italic) : le TUI utilise
  une icône Nerd Font (le bouton "internet") qui n'existe pas dans une
  police classique — sans MesloLGS NF, ce caractère s'affiche comme un
  carré vide. **Rien à faire manuellement** : les fichiers sont embarqués
  dans le dépôt (`fonts/MesloLGS NF/`, voir `fonts/README.md`) et installés
  automatiquement pour l'utilisateur courant au premier lancement. Sur
  Konsole et Windows Terminal, le TUI configure aussi lui-même un profil
  dédié avec cette police (voir "Lancer l'application") ; sur un autre
  émulateur, la police est installée mais reste à sélectionner
  manuellement dans les réglages du terminal (un TUI ne peut pas imposer
  sa police à un terminal qu'il ne pilote pas lui-même).
