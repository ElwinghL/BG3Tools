"""Mise en état optimal du préfixe Proton de BG3 pour nos outils tiers
(LSLib, BG3 Mod Manager, Load Order Optimizer, Para Tool...), sans jamais
affecter BG3 lui-même.

Deux principes de sécurité :
- Les changements de version Windows rapportée sont appliqués par
  exécutable (`HKCU\\Software\\Wine\\AppDefaults\\<exe>`), jamais
  globalement — BG3 (bg3.exe/bg3_dx11.exe) n'est jamais dans la liste des
  exécutables concernés par cette fonction.
- Certains installeurs .NET (via winetricks/protontricks, ex: dotnet452)
  basculent temporairement la version Windows globale du préfixe sur
  "Windows 2003" le temps de l'installation ("Setting Windows version to
  2003, otherwise applications using .NET 4.5 will subtly fail" — message
  normal de winetricks) puis la restaurent. On vérifie malgré tout, après
  coup, qu'aucun override global n'est resté accroché, par sécurité.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

LogFn = Callable[[str], None]

# Verbes winetricks couvrant les besoins courants de nos outils (WPF/.NET,
# rendu de texte) sans forcer d'installation .NET Framework ancienne
# (dotnet452 et consorts) tant qu'aucun de nos outils ne le requiert
# explicitement — évite le bascule transitoire en "Windows 2003" quand ce
# n'est pas nécessaire.
DEFAULT_TOOL_VERBS = ["vcrun2022", "corefonts"]

TOOL_WINDOWS_VERSION = "win10"


class WinePrefixError(RuntimeError):
    pass


def _run_wine_reg(
    wine_bin: str, prefix: Path, args: list[str], *, timeout: int = 30
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    try:
        return subprocess.run(
            [wine_bin, "reg", *args],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WinePrefixError(f"Timeout lors de l'appel à 'wine reg {' '.join(args)}'.") from exc
    except OSError as exc:
        raise WinePrefixError(f"Échec de l'appel à 'wine reg {' '.join(args)}' : {exc}") from exc


def set_app_windows_version(
    wine_bin: str, prefix: Path, exe_name: str, version: str = TOOL_WINDOWS_VERSION
) -> None:
    """Force la version Windows rapportée à `version` uniquement pour
    `exe_name` (ex: 'BG3ModManager.exe'), sans toucher au reste du préfixe."""
    key = rf"HKCU\Software\Wine\AppDefaults\{exe_name}"
    result = _run_wine_reg(wine_bin, prefix, ["add", key, "/v", "Version", "/d", version, "/f"])
    if result.returncode != 0:
        raise WinePrefixError(
            f"Échec de configuration de la version Windows pour '{exe_name}' : "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def clear_global_windows_version_override(wine_bin: str, prefix: Path) -> bool:
    """Vérifie qu'aucune version Windows n'est forcée globalement sur le
    préfixe (résidu possible d'une installation .NET interrompue), et la
    supprime le cas échéant. Retourne True si un override a été trouvé et
    supprimé, False si le préfixe était déjà propre."""
    key = r"HKCU\Software\Wine"
    query = _run_wine_reg(wine_bin, prefix, ["query", key, "/v", "Version"])
    if query.returncode != 0:
        # Valeur absente = pas d'override global, c'est l'état attendu.
        return False
    delete = _run_wine_reg(wine_bin, prefix, ["delete", key, "/v", "Version", "/f"])
    if delete.returncode != 0:
        raise WinePrefixError(
            "Un override de version Windows global a été détecté mais n'a "
            f"pas pu être supprimé : {delete.stderr.strip() or delete.stdout.strip()}"
        )
    return True


def run_winetricks_verbs(
    appid: str, verbs: list[str], *, log_dir: Path | None = None, timeout: int = 900
) -> None:
    """Installe les composants `verbs` (ex: 'vcrun2022', 'corefonts') dans
    le préfixe Proton de l'appid donné, via protontricks en mode silencieux
    (`-q`, sans fenêtre). Bloquant — à appeler depuis un worker en arrière-plan."""
    protontricks_bin = shutil.which("protontricks")
    if protontricks_bin is None:
        raise WinePrefixError("Le binaire 'protontricks' est introuvable dans le PATH.")

    args = [protontricks_bin, appid, "-q", *verbs]
    try:
        result = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise WinePrefixError(
            f"Timeout ({timeout}s) lors de l'installation de {', '.join(verbs)} via protontricks."
        ) from exc

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "protontricks.log"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"$ {' '.join(args)}\n")
            fh.write(result.stdout)
            fh.write(result.stderr)

    if result.returncode != 0:
        raise WinePrefixError(
            f"Échec de l'installation de {', '.join(verbs)} via protontricks "
            f"(code {result.returncode}). Voir le log pour le détail."
        )


def optimize_prefix_for_tools(
    *,
    appid: str,
    wine_bin: str,
    prefix: Path,
    tool_executables: list[Path],
    verbs: list[str] = DEFAULT_TOOL_VERBS,
    log_dir: Path | None = None,
    log: LogFn = lambda _msg: None,
) -> None:
    """Met le préfixe Proton de BG3 dans un état adapté à nos outils tiers :
    - installe les composants Windows courants dont ils ont besoin
      (`verbs`, silencieusement, via protontricks) ;
    - force une version Windows moderne pour chaque exécutable outil
      trouvé (par exécutable, jamais globalement — BG3 n'est jamais visé) ;
    - vérifie qu'aucune version Windows n'est restée forcée globalement
      (résidu d'une précédente installation .NET, ex: dotnet452 qui bascule
      temporairement le préfixe en "Windows 2003").
    """
    if verbs:
        log(f"Installation de {', '.join(verbs)} via protontricks (silencieux)...")
        run_winetricks_verbs(appid, verbs, log_dir=log_dir)
        log(f"{', '.join(verbs)} installé(s).")

    for exe in tool_executables:
        set_app_windows_version(wine_bin, prefix, exe.name)
        log(f"Version Windows ({TOOL_WINDOWS_VERSION}) forcée pour '{exe.name}'.")

    if clear_global_windows_version_override(wine_bin, prefix):
        log(
            "[#D8C091]Un override de version Windows global résiduel a été "
            "détecté et supprimé (BG3 utilisera de nouveau la version par "
            "défaut du préfixe).[/#D8C091]"
        )
    else:
        log("Aucun override de version Windows global résiduel — préfixe propre.")
