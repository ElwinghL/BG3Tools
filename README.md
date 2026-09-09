# BG3 Mod TUI — v1.0.0

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

Une clé API Nexus Mods (`NEXUS_API_KEY`) et/ou mod.io (`MODIO_API_KEY`,
`MOD_IO_USER_ID`) sont nécessaires pour le téléchargement — voir
`.env.example`.

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

## Prérequis

- Python ≥ 3.11
- Sous Linux : `protontricks` (menu "Ouvrir protontricks") pour les
  réglages Wine du préfixe BG3.
