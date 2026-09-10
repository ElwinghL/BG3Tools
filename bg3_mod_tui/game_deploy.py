"""Déploiement des DLL d'outils (Native Mod Loader, BG3 Script Extender)
dans le dossier bin/ d'installation du jeu — étape distincte du simple
téléchargement dans Tools/, car elle touche à l'installation réelle de BG3.

BG3 Script Extender s'installe en plaçant sa DLL sous le nom `DWrite.dll`
dans bin/ (hijack du chargement de dwrite.dll par le jeu), avec un fichier
`ScriptExtenderSettings.json` optionnel à côté pour la configuration (voir
https://github.com/Norbyte/bg3se).

Native Mod Loader s'installe en remplaçant `bink2w64.dll` (vidéo) par son
propre loader dans bin/ (l'original est sauvegardé par l'outil lui-même
sous `bink2w64_original.dll`).

Sous Linux/Proton, ces DLL Windows ne sont chargées par le jeu que si Wine
est configuré pour les traiter comme "native" via WINEDLLOVERRIDES ; cela
se règle dans les options de lancement Steam du jeu, que ce script ne peut
pas modifier automatiquement (fichier de configuration Steam, à modifier
manuellement) — un rappel est donc journalisé plutôt qu'appliqué.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from bg3_mod_tui.platform_utils import is_windows, link_or_symlink

LogFn = Callable[[str], None]

NATIVE_MOD_LOADER_DIR_NAME = "Native Mod Loader"
SCRIPT_EXTENDER_DIR_NAME = "BG3 Script Extender"
SCRIPT_EXTENDER_DLL_TARGET_NAME = "DWrite.dll"
SCRIPT_EXTENDER_SETTINGS_NAME = "ScriptExtenderSettings.json"

# Valeurs par défaut documentées dans le README du Script Extender.
SCRIPT_EXTENDER_DEFAULT_SETTINGS = {
    "CreateConsole": False,
    "EnableLogging": False,
    "LogRuntime": False,
    "LogCompile": False,
    "LogFailedCompile": True,
    "LogDirectory": r"My Documents\OsirisLogs",
    "EnableExtensions": True,
    "SendCrashReports": True,
    "DeveloperMode": False,
    "DisableModValidation": True,
    "EnableAchievements": True,
    "EnableDebugger": False,
    "DebuggerPort": 9999,
    "EnableLuaDebugger": False,
    "LuaDebuggerPort": 9998,
}

STEAM_LAUNCH_OPTION_REMINDER = (
    'WINEDLLOVERRIDES="DWrite.dll=n,b" %command% --skip-launcher'
)


NML_HOOKED_DLL_NAME = "bink2w64.dll"
NML_BACKUP_DLL_NAME = "bink2w64_original.dll"


def _replace_with_hardlink_backup(target: Path, source: Path, backup: Path, *, log: LogFn) -> None:
    """Fait de `target` un hardlink vers `source` (notre DLL gérée). Si
    `target` existe déjà et n'est pas déjà ce hardlink, il est d'abord
    sauvegardé sous `backup` (le vrai binaire original du jeu n'est
    sauvegardé qu'une seule fois — un `backup` déjà présent n'est jamais
    écrasé)."""
    if target.exists() and target.stat().st_ino == source.stat().st_ino:
        log(f"  '{target.name}' déjà un hardlink vers '{source}', rien à faire.")
        return

    if target.exists():
        if not backup.exists():
            shutil.move(str(target), str(backup))
            log(f"  original sauvegardé : '{target.name}' -> '{backup.name}'")
        else:
            target.unlink()
    link_or_symlink(source, target)
    log(f"  '{target.name}' remplacé par un hardlink vers notre copie.")


def deploy_native_mod_loader(tools_dir: Path, game_bin_dir: Path, *, log: LogFn) -> None:
    """Installe Native Mod Loader dans le dossier bin/ du jeu :
    `bink2w64.dll` (notre copie gérée dans Tools/) remplace celui du jeu,
    en sauvegardant l'original sous `bink2w64_original.dll` s'il ne l'a
    pas déjà été. Les éventuels autres fichiers du loader sont copiés
    normalement."""
    source_bin = tools_dir / NATIVE_MOD_LOADER_DIR_NAME / "bin"
    if not source_bin.is_dir() or not any(source_bin.iterdir()):
        log(
            "[Native Mod Loader] rien à déployer : "
            f"'{source_bin}' est vide ou absent (installation manuelle requise)."
        )
        return

    if not game_bin_dir.is_dir():
        log(f"[Native Mod Loader] dossier bin/ du jeu introuvable : {game_bin_dir}")
        return

    log(f"[Native Mod Loader] déploiement vers {game_bin_dir}...")

    source_hooked_dll = source_bin / NML_HOOKED_DLL_NAME
    if source_hooked_dll.is_file():
        target_dll = game_bin_dir / NML_HOOKED_DLL_NAME
        backup_dll = game_bin_dir / NML_BACKUP_DLL_NAME
        _replace_with_hardlink_backup(target_dll, source_hooked_dll, backup_dll, log=log)
    else:
        log(f"  '{NML_HOOKED_DLL_NAME}' absent de {source_bin}, non déployé.")

    other_files = [
        p
        for p in source_bin.rglob("*")
        if p.is_file() and p.name not in (NML_HOOKED_DLL_NAME, NML_BACKUP_DLL_NAME)
    ]
    for item in other_files:
        relative = item.relative_to(source_bin)
        target = game_bin_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        log(f"  copié : {relative}")

    log(f"[Native Mod Loader] terminé ({len(other_files)} fichier(s) additionnel(s) copié(s)).")


def _hardlink_replace(target: Path, source: Path, *, log: LogFn) -> None:
    """Fait de `target` un hardlink vers `source`. Si `target` existe déjà
    (fichier différent), il est simplement remplacé — utilisé pour des
    fichiers gérés par nous (pas de notion d'« original du jeu » à
    préserver, contrairement à `_replace_with_hardlink_backup`)."""
    if target.exists() and target.stat().st_ino == source.stat().st_ino:
        log(f"  '{target.name}' déjà un hardlink vers '{source}', rien à faire.")
        return
    if target.exists():
        target.unlink()
    link_or_symlink(source, target)
    log(f"  '{target.name}' relié (hardlink) à notre copie gérée.")


def deploy_script_extender(tools_dir: Path, game_bin_dir: Path, *, log: LogFn) -> None:
    """Installe le Script Extender dans le dossier bin/ du jeu : notre
    copie gérée de la DLL (Tools/BG3 Script Extender/) est reliée par
    hardlink vers `bin/DWrite.dll`, de même pour
    `ScriptExtenderSettings.json` (créé avec les valeurs par défaut du
    README s'il n'existe pas encore côté Tools/ — une configuration déjà
    déployée dans bin/ est migrée vers Tools/ plutôt qu'écrasée, pour ne
    jamais perdre un réglage personnalisé)."""
    source_dir = tools_dir / SCRIPT_EXTENDER_DIR_NAME
    if not source_dir.is_dir():
        log(f"[BG3 Script Extender] dossier introuvable : {source_dir}")
        return

    dlls = [
        d for d in source_dir.glob("*.dll") if d.name != SCRIPT_EXTENDER_SETTINGS_NAME
    ]
    if not dlls:
        log(f"[BG3 Script Extender] aucune DLL trouvée dans {source_dir}.")
        return
    source_dll = next((d for d in dlls if d.name.lower() == "dwrite.dll"), dlls[0])

    if not game_bin_dir.is_dir():
        log(f"[BG3 Script Extender] dossier bin/ du jeu introuvable : {game_bin_dir}")
        return

    log(f"[BG3 Script Extender] déploiement vers {game_bin_dir}...")

    target_dll = game_bin_dir / SCRIPT_EXTENDER_DLL_TARGET_NAME
    _hardlink_replace(target_dll, source_dll, log=log)

    managed_settings = source_dir / SCRIPT_EXTENDER_SETTINGS_NAME
    target_settings = game_bin_dir / SCRIPT_EXTENDER_SETTINGS_NAME
    if not managed_settings.exists():
        if target_settings.exists():
            shutil.copy2(target_settings, managed_settings)
            log(f"  configuration déjà déployée migrée vers {managed_settings}")
        else:
            managed_settings.write_text(
                json.dumps(SCRIPT_EXTENDER_DEFAULT_SETTINGS, indent=4) + "\n", encoding="utf-8"
            )
            log(f"  configuration par défaut créée : {managed_settings}")
    else:
        log(f"  configuration gérée existante conservée : {managed_settings}")

    _hardlink_replace(target_settings, managed_settings, log=log)

    log("[BG3 Script Extender] terminé.")

    if not is_windows():
        log(
            "[BG3 Script Extender] Linux/Proton : ajoute ceci aux options de "
            f"lancement Steam du jeu : {STEAM_LAUNCH_OPTION_REMINDER}"
        )


def deploy_loose_files(managed_dir: Path, game_data_dir: Path, *, log: LogFn) -> int:
    """Relie par hardlink chaque fichier de `managed_dir` (notre copie
    gérée et permanente des mods "loose files", structurée comme Data/ du
    jeu — ex: managed_dir/Generated/..., managed_dir/Public/.../Generated/...)
    vers son équivalent sous `game_data_dir`, en créant les dossiers
    intermédiaires nécessaires. Idempotent (ne touche pas un lien déjà à
    jour). Retourne le nombre de fichiers reliés."""
    if not managed_dir.is_dir():
        return 0
    if not game_data_dir.is_dir():
        log(f"[Mods loose files] dossier Data/ du jeu introuvable : {game_data_dir}")
        return 0

    count = 0
    for item in managed_dir.rglob("*"):
        if item.is_dir():
            continue
        target = game_data_dir / item.relative_to(managed_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        _hardlink_replace(target, item, log=log)
        count += 1
    return count


def remove_stale_hardlinks(target_dir: Path, stale_names: set[str], *, log: LogFn) -> int:
    """Supprime, sous `target_dir`, les fichiers dont le nom (ou chemin
    relatif) figure dans `stale_names` — utilisé lors d'un changement de
    profil pour défaire uniquement les hardlinks qu'on sait avoir créés
    pour le profil quitté (voir `profiles.load_profile_hardlinks`) et qui
    ne font plus partie du nouveau profil, sans jamais toucher aux autres
    fichiers de `target_dir` (ex: les DLL propres à Native Mod Loader / au
    Script Extender, non suivies par profil, ou tout fichier du jeu lui-même).
    Retourne le nombre de fichiers effectivement supprimés."""
    if not target_dir.is_dir():
        return 0
    removed = 0
    for name in sorted(stale_names):
        path = target_dir / name
        if path.is_file():
            path.unlink()
            log(f"  hardlink retiré (ne fait plus partie du profil) : {name}")
            removed += 1
    return removed


def sync_hardlinked_files(
    managed_dir: Path,
    target_dir: Path,
    wanted: set[str],
    previously_linked: set[str],
    *,
    log: LogFn,
) -> set[str]:
    """Aligne les hardlinks sous `target_dir` sur `wanted` (chemins relatifs
    communs à `managed_dir` et `target_dir`, ex: les fichiers "loose" d'un
    profil vers Data/ du jeu) sans tout supprimer/recréer sans discernement :
    seules les entrées de `previously_linked` (ce qu'on sait avoir relié pour
    le profil quitté, voir `profiles.load_profile_hardlinks`) qui ne sont
    plus dans `wanted` sont retirées de `target_dir` (voir
    `remove_stale_hardlinks`) — un fichier de `target_dir` absent de
    `previously_linked` n'est jamais touché. Chaque entrée de `wanted` est
    ensuite (re)reliée depuis `managed_dir` si sa source existe encore
    (idempotent, voir `_hardlink_replace`) ; une source manquante est
    seulement journalisée (mod supprimé du stockage géré global).
    Retourne le sous-ensemble de `wanted` effectivement relié — à
    sauvegarder comme nouveau `previously_linked` du profil actif (voir
    `profiles.save_profile_hardlinks`)."""
    remove_stale_hardlinks(target_dir, previously_linked - wanted, log=log)

    linked: set[str] = set()
    if not managed_dir.is_dir():
        return linked
    target_dir.mkdir(parents=True, exist_ok=True)
    for rel in sorted(wanted):
        source = managed_dir / rel
        if not source.is_file():
            log(f"  source absente pour '{rel}', hardlink non (re)créé.")
            continue
        target = target_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        _hardlink_replace(target, source, log=log)
        linked.add(rel)
    return linked
