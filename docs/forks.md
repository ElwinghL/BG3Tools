# Forks `ElwinghL/*` utilisés par ce projet

Deux dépendances externes sont patchées via des forks GitHub personnels
plutôt que d'ouvrir des PR upstream directement. Ce document résume pourquoi
et où en est chaque fork ; le détail complet (patchs, commits, tests) reste
dans `.claude/TODO.md` (§11b/11c pour bg3se, §19 pour lslib).

## `ElwinghL/bg3se` (fork de `Norbyte/bg3se`)

- **Sous-module** : `Tools/BG3 Script Extender/` (déjà basculé sur le fork,
  voir `Tools/TOOLS.md`).
- **Pourquoi** : la console interactive BG3SE (REPL Lua) passe par la console
  Win32 native, laggy sous le rendu GUI de Wine/Proton. Objectif : exposer
  cette console via un socket TCP en boucle locale (127.0.0.1) — transparent
  à travers Proton, sur le même modèle que le socket déjà utilisé par le
  débogueur Osiris/Lua (`SocketInterface`/`DebugInterface.cpp`).
- **État** : patch C++ écrit (`RemoteConsole.{h,cpp}`, protocole texte à
  tags, port 9997 par défaut) sur une branche locale **non poussée**
  (`feat/RemoteConsoleSocket`), faute de toolchain Windows dans cet
  environnement pour le builder/tester. Le pointeur de sous-module du dépôt
  parent n'a pas été mis à jour vers ce commit. Côté client Python
  (`bg3_mod_tui/bg3se_remote_console.py` + `widgets/bg3se_console.py`),
  déjà testé et intégré à l'UI, prêt à parler au vrai process dès que le
  patch C++ sera buildé.

## `ElwinghL/lslib` (fork de `Norbyte/lslib`)

- **Sous-module** : `Tools/ExportTools/` (**toujours sur `Norbyte/lslib`** à
  ce jour — la bascule n'a pas encore eu lieu, voir "Reste à faire"
  ci-dessous).
- **Pourquoi** : LSLib/Divine.exe n'a pas de build Linux officiel. Objectif
  du fork, volontairement restreint : lire/écrire/éditer des `.pak` — rien
  d'autre (Story/Osiris, GR2/Granny, VirtualTextures et savegames sont
  sacrifiés, ces parties nécessitant MSVC ou des générateurs de parseurs
  Windows-only sans équivalent Linux).
- **État** : build Linux fonctionnel obtenu (`dotnet build` → 0 erreur,
  `Divine.dll` exécutable), périmètre réduit au pak/resource/loca. Deux bugs
  Linux découverts et corrigés au passage (crash `extract-packages` en mode
  batch ; `TryToValidatePath` qui plantait sur tout chemin absolu Unix).
  Branche `fix/LinuxBuildPakOnlyScope` **poussée** sur le fork
  (2026-09-13, PR non ouverte :
  https://github.com/ElwinghL/lslib/pull/new/fix/LinuxBuildPakOnlyScope).
  Script de build reproductible :
  `scripts/lslib_fork_linux_build/build_lslib_fork_linux.sh`.
- **Limite connue non résolue** : packager (`create-package`) depuis une
  source vivant sur le point de montage `M2` (racine de ce projet) produit
  un `.pak` illisible, cause racine non identifiée (probable particularité
  mmap/lecture de fichier de ce point de montage sous ce build .NET).
  Contournement : stager la source ailleurs (`/tmp`) avant `create-package`.
- **Reste à faire (§19c du TODO)** : une fois la branche relue/mergée côté
  fork par Elwingh — basculer le sous-module `Tools/ExportTools` vers
  `ElwinghL/lslib`, mettre à jour `Tools/TOOLS.md`, re-épingler le commit,
  et relancer `scripts/compare_pak_reader.py --divine-mode batch`
  (`THIRD_PARTY_LICENSES.md` à ajuster aussi si la source du binaire
  change).

## Règle commune

Aucun push vers un remote partagé (fork inclus) sans autorisation explicite
d'Elwingh au moment du push — les branches ci-dessus restées locales le sont
pour cette raison, pas par oubli.
