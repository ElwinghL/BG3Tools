"""Relie par hardlink les .pak des ponts NMCM (`Tools/nmcm_patches/*/dist/
*.pak`, voir Tools/bg3-nmcm) vers le dossier Mods géré.

Ces .pak sont déjà construits (contrairement à `ModFixer.pak`, empaqueté à
la volée via Divine.exe dans `mod_fixer_fork.py`) : il suffit de les
relier, comme `native_mods.py` le fait pour les DLL. La découverte se fait
entièrement par recherche sur le système de fichiers -- tout nouveau pont
ajouté plus tard sous `Tools/nmcm_patches/<Nom>/dist/*.pak` est pris en
compte automatiquement, sans qu'il soit besoin de modifier ce module."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bg3_mod_tui.platform_utils import link_or_symlink

LogFn = Callable[[str], None]

NMCM_PATCHES_DIRNAME = "nmcm_patches"


def discover_bridge_paks(tools_dir: Path) -> list[Path]:
    """Renvoie chaque .pak sous `Tools/nmcm_patches/*/dist/*.pak`, trié par
    nom pour un ordre de traitement stable. Liste vide si le dossier
    n'existe pas (sous-module/dossier non présent)."""
    patches_dir = tools_dir / NMCM_PATCHES_DIRNAME
    if not patches_dir.is_dir():
        return []
    return sorted(patches_dir.glob("*/dist/*.pak"))


def _link_pak(dest_dir: Path, source: Path, *, log: LogFn) -> bool:
    """Relie `source` vers `dest_dir/source.name` (voir `link_or_symlink`
    pour le repli symlink si hardlink impossible -- EXDEV). Retourne
    `True` si un lien a été (re)créé, `False` si déjà en place (même
    inode -- idempotent, comme `native_mods._hardlink_into`)."""
    target = dest_dir / source.name
    if target.exists():
        if target.stat().st_ino == source.stat().st_ino:
            log(f"  '{target.name}' déjà relié vers '{source}', rien à faire.")
            return False
        target.unlink()
    link_or_symlink(source, target)
    log(f"  '{target.name}' relié vers {dest_dir}.")
    return True


def deploy_nmcm_bridges(
    mods_dir: Path,
    tools_dir: Path,
    *,
    log: LogFn = lambda _msg: None,
) -> list[Path]:
    """Relie par hardlink chaque pont NMCM découvert sous
    `Tools/nmcm_patches/*/dist/*.pak` vers `mods_dir`. Retourne la liste
    des .pak sources effectivement (re)liés lors de cet appel (les ponts
    déjà en place, inode identique, ne sont pas comptés)."""
    paks = discover_bridge_paks(tools_dir)
    if not paks:
        log(f"Aucun pont NMCM trouvé sous {tools_dir / NMCM_PATCHES_DIRNAME}/*/dist/.")
        return []

    mods_dir.mkdir(parents=True, exist_ok=True)
    log(f"{len(paks)} pont(s) NMCM trouvé(s) -> {mods_dir}")
    linked = [pak for pak in paks if _link_pak(mods_dir, pak, log=log)]
    return linked
