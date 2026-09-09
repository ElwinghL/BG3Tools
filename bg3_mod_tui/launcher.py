"""Lancement des outils tiers (.exe) installés sous Tools/.

Sur Windows, l'exécutable est lancé directement. Sous Linux, le lancement
est restreint au préfixe Proton de BG3 (celui dans lequel ce projet vit
déjà, sous `compatdata/<appid>/pfx`) plutôt qu'à un Wine générique du
système, afin de garantir un environnement cohérent avec le jeu (mêmes
DLL, mêmes overrides Wine, etc.).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from bg3_mod_tui.platform_utils import find_proton_prefix, find_proton_wine_bin, is_windows


class LauncherError(RuntimeError):
    pass


def _popen_detached(
    args: list[str], *, cwd: str, env: dict | None = None, log_file: Path | None = None
) -> None:
    """Lance `args` en arrière-plan, complètement détaché du terminal du
    TUI : ni le blocage de l'appelant (Popen ne fait qu'initier le
    processus), ni la survie du processus enfant ne dépendent du TUI (un
    Ctrl+C ou une fermeture du terminal du TUI ne l'affecte pas).

    La sortie du processus est redirigée vers `log_file` si fourni (utile
    pour diagnostiquer un échec silencieux — ex: outil Windows qui plante
    immédiatement), sinon jetée."""
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        out = log_file.open("ab")
        stdout = stderr = out
    else:
        stdout = stderr = subprocess.DEVNULL

    kwargs: dict = {
        "cwd": cwd,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": stdout,
        "stderr": stderr,
    }
    if is_windows():
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def resolve_wine_bin(prefix: Path) -> str:
    """Retrouve le binaire `wine` à utiliser : en priorité celui fourni par
    la version de Proton associée au préfixe (le seul garanti compatible
    avec celui-ci), sinon un `wine` système en repli."""
    proton_wine = find_proton_wine_bin(prefix)
    if proton_wine is not None:
        return str(proton_wine)
    system_wine = shutil.which("wine") or shutil.which("wine64")
    if system_wine is None:
        raise LauncherError(
            "Aucun binaire 'wine' trouvé : ni celui de la version de Proton "
            "utilisée par BG3, ni de 'wine' système dans le PATH."
        )
    return system_wine


def launch_tool(exe_path: Path, *, reference_path: Path, log_dir: Path | None = None) -> None:
    """Lance `exe_path` en tâche de fond, détachée du TUI (le TUI reste
    utilisable immédiatement, et fermer le TUI n'arrête pas l'outil).
    `reference_path` (ex: dossier AppData de BG3) sert à localiser le
    préfixe Proton de BG3 sous Linux. Si `log_dir` est fourni, la sortie de
    l'outil y est journalisée (utile en cas d'échec silencieux)."""
    if not exe_path.is_file():
        raise LauncherError(f"Exécutable introuvable : {exe_path}")

    log_file = log_dir / f"{exe_path.stem}.log" if log_dir else None

    if is_windows():
        _popen_detached([str(exe_path)], cwd=str(exe_path.parent), log_file=log_file)
        return

    prefix = find_proton_prefix(reference_path) or find_proton_prefix(exe_path)
    if prefix is None:
        raise LauncherError(
            "Impossible de déterminer le préfixe Proton de BG3 ; lancement "
            "refusé (par sécurité, seul le préfixe Proton de BG3 est autorisé)."
        )

    wine_bin = resolve_wine_bin(prefix)

    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    _popen_detached(
        [wine_bin, str(exe_path)], cwd=str(exe_path.parent), env=env, log_file=log_file
    )


def open_protontricks(reference_path: Path, *, log_dir: Path | None = None) -> None:
    """Ouvre protontricks (interface winetricks) sur le préfixe Proton de
    BG3. Contrairement à winetricks appelé directement, protontricks
    identifie le jeu par son AppID Steam et gère lui-même le Steam Runtime,
    le wineserver et les variables d'environnement associées — plus fiable
    que reconstituer WINEPREFIX/WINE à la main. Linux uniquement.
    Si `log_dir` est fourni, la sortie y est journalisée."""
    if is_windows():
        raise LauncherError("protontricks n'est disponible que sous Linux.")

    prefix = find_proton_prefix(reference_path)
    if prefix is None:
        raise LauncherError("Impossible de déterminer le préfixe Proton de BG3.")

    appid = prefix.parent.name
    if not appid.isdigit():
        raise LauncherError(
            f"AppID Steam introuvable à partir du préfixe ({prefix} attendu sous compatdata/<appid>/pfx)."
        )

    protontricks_bin = shutil.which("protontricks")
    if protontricks_bin is None:
        raise LauncherError("Le binaire 'protontricks' est introuvable dans le PATH.")

    log_file = log_dir / "protontricks.log" if log_dir else None
    # `protontricks APPID` sans commande ni `--gui` se contente d'afficher
    # l'aide (code de retour 0, silencieusement) : il faut `--gui` explicite
    # (avant l'AppID) pour ouvrir l'interface winetricks du jeu.
    _popen_detached(
        [protontricks_bin, "--gui", appid], cwd=str(prefix), log_file=log_file
    )
