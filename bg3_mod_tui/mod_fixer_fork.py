"""Construit `ModFixer.pak` (repackaging propre de Mod Fixer, meta.lsx
valide) directement depuis le sous-module git `Tools/ModFixer`
(github.com/ElwinghL/ModFixer, MIT -- voir son README pour l'attribution
complète à figs999, auteur du mod d'origine sur Nexus Mods #141, et à
Norbyte/BG3SE pour la technique elle-même).

Avant l'ajout de ce sous-module, ce module extrayait le `.pak` que
l'utilisateur devait avoir installé depuis Nexus Mods au préalable
(`extract-package` via Divine.exe) pour en retirer le fichier déclencheur
et le remballer sous un `meta.lsx` propre. `Tools/ModFixer/Mods/` contient
maintenant directement ce module complet (meta.lsx + fichier déclencheur
vide) : il suffit de l'empaqueter (`create-package`), sans dépendre d'une
installation Nexus préexistante ni d'extraire quoi que ce soit."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from bg3_mod_tui.compat_framework import find_divine_exe
from bg3_mod_tui.launcher import resolve_wine_bin
from bg3_mod_tui.platform_utils import find_proton_prefix, is_windows, to_wine_path

LogFn = Callable[[str], None]

ORIGINAL_PAK_NAME = "ModFixer.pak"
# Sauvegarde d'un éventuel ModFixer.pak préexistant (installé manuellement
# par l'utilisateur avant ce sous-module), écrite une seule fois, pour
# pouvoir revenir en arrière -- jamais retouchée ensuite.
ORIGINAL_BACKUP_NAME = "ModFixer.pak.orig"

_DIVINE_TIMEOUT_SECONDS = 60


class ModFixerForkError(RuntimeError):
    pass


def _divine_command(
    divine_exe: Path, action: str, extra_args: list[str], *, reference_path: Path
) -> tuple[list[str], dict[str, str] | None]:
    """Construit la commande Divine.exe (+ environnement Wine si besoin),
    identique dans son principe à `pak_metadata._run_divine`/
    `compat_framework.build_pak` : sous Linux, Divine.exe (.NET) valide ses
    chemins via `System.Uri` et rejette un chemin Unix brut, d'où la
    conversion en chemin Windows (`to_wine_path`) pour tout argument de
    chemin passé dans `extra_args`."""
    if is_windows():
        return [str(divine_exe), "-g", "bg3", "-a", action, *extra_args], None

    prefix = find_proton_prefix(reference_path)
    if prefix is None:
        raise ModFixerForkError("Impossible de déterminer le préfixe Proton de BG3.")
    wine_bin = resolve_wine_bin(prefix)
    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    return [wine_bin, str(divine_exe), "-g", "bg3", "-a", action, *extra_args], env


def _run_divine(
    divine_exe: Path, action: str, extra_args: list[str], *, reference_path: Path
) -> None:
    command, env = _divine_command(divine_exe, action, extra_args, reference_path=reference_path)
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_DIVINE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ModFixerForkError(f"Timeout Divine.exe ({action}) : {exc}") from exc
    except OSError as exc:
        raise ModFixerForkError(f"Échec du lancement de Divine.exe : {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"code {result.returncode}"
        raise ModFixerForkError(f"Échec Divine.exe ({action}) : {detail}")


def build_fork(
    mods_dir: Path,
    tools_dir: Path,
    *,
    reference_path: Path,
    log: LogFn = lambda _msg: None,
) -> Path:
    """Empaquette `Tools/ModFixer/Mods/` en `ModFixer.pak` dans `mods_dir`,
    en remplacement d'un éventuel `ModFixer.pak` déjà présent (sauvegardé
    une seule fois en `ModFixer.pak.orig`, pour rester réversible).

    Lève `ModFixerForkError` si le sous-module `Tools/ModFixer` ou
    Divine.exe sont introuvables, ou si l'empaquetage échoue."""
    dest_pak = mods_dir / ORIGINAL_PAK_NAME
    backup_pak = mods_dir / ORIGINAL_BACKUP_NAME

    source_root = tools_dir / "ModFixer"
    if not (source_root / "Mods").is_dir():
        raise ModFixerForkError(
            f"{source_root / 'Mods'} introuvable -- sous-module Tools/ModFixer manquant "
            "ou non initialisé (git submodule update --init Tools/ModFixer)."
        )

    divine_exe = find_divine_exe(tools_dir)
    if divine_exe is None:
        raise ModFixerForkError(
            "Divine.exe introuvable sous Tools/ExportTools/ — télécharge d'abord "
            "LSLib via « MAJ des outils »."
        )

    use_wine_path = not is_windows()

    if dest_pak.is_file() and not backup_pak.is_file():
        shutil.copy2(dest_pak, backup_pak)
        log(f"Original conservé -> {backup_pak} (avant première réécriture).")

    log(f"Empaquetage de {ORIGINAL_PAK_NAME} depuis Tools/ModFixer via Divine.exe...")
    _run_divine(
        divine_exe,
        "create-package",
        [
            "-s",
            to_wine_path(source_root) if use_wine_path else str(source_root),
            "-d",
            to_wine_path(dest_pak) if use_wine_path else str(dest_pak),
        ],
        reference_path=reference_path,
    )

    if not dest_pak.is_file():
        raise ModFixerForkError(f"Échec de l'empaquetage : {dest_pak} n'a pas été créé.")

    log(f"{ORIGINAL_PAK_NAME} construit -> {dest_pak}.")
    return dest_pak
