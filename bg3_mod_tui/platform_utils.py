"""Détection de plateforme et gestion des privilèges (admin Windows)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_windows() -> bool:
    return sys.platform == "win32"


def has_graphical_display() -> bool:
    """Indique si un environnement de bureau graphique semble disponible,
    pour proposer un bouton "ouvrir dans le navigateur" plutôt qu'un
    simple lien à copier à la main (cas d'une session headless/SSH, où
    `webbrowser.open` échouerait silencieusement ou ouvrirait un
    navigateur texte inattendu)."""
    if is_windows():
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def is_admin() -> bool:
    """Indique si le processus courant a les privilèges nécessaires pour
    créer des liens symboliques / hardlinks.

    - Windows : nécessite un jeton administrateur (sauf si le mode
      développeur est activé, auquel cas les symlinks ne nécessitent pas
      d'élévation — mais on ne peut pas le garantir simplement, donc on
      recommande l'élévation par sécurité et on retente en cas d'échec).
    - Linux : la création de liens symboliques ne nécessite aucun privilège
      particulier sur le système de fichiers de l'utilisateur.
    """
    if is_windows():
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return True


def relaunch_as_admin() -> bool:
    """Relance le script courant avec élévation de privilèges (UAC) sur
    Windows. Retourne True si la relance a été déclenchée (le process
    courant doit alors se terminer), False si l'élévation a échoué ou
    n'est pas applicable.
    """
    if not is_windows():
        return False

    try:
        import ctypes

        params = " ".join(f'"{arg}"' for arg in sys.argv)
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1
        )
        # ShellExecuteW renvoie une valeur > 32 en cas de succès.
        return ret > 32
    except Exception:
        return False


def windows_dev_mode_enabled() -> bool:
    """Vérifie si le mode développeur Windows est activé (permet de créer
    des liens symboliques sans élévation, pour les utilisateurs standards).
    """
    if not is_windows():
        return False

    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock",
        )
        value, _ = winreg.QueryValueEx(key, "AllowDevelopmentWithoutDevLicense")
        return bool(value)
    except Exception:
        return False


def can_create_links_without_admin() -> bool:
    """Retourne True si l'utilisateur peut créer des liens symboliques sans
    élévation (Linux, ou Windows en mode développeur / déjà admin)."""
    if not is_windows():
        return True
    return is_admin() or windows_dev_mode_enabled()


def find_proton_prefix(start_path: Path) -> Path | None:
    """Recherche, parmi les dossiers parents de `start_path`, le préfixe
    Proton de BG3 (un dossier `pfx` contenant `drive_c`). Utilisé pour
    restreindre le lancement d'outils Windows, sous Linux, au préfixe de
    BG3 plutôt qu'à un Wine générique.

    `start_path` est résolu (`.resolve()`) avant la recherche : un raccourci
    pratique comme `~/ProtonGames/<jeu>/` pointe souvent (lien symbolique)
    directement vers `.../pfx/drive_c/users/steamuser`, sans qu'aucun
    segment du chemin *non résolu* ne s'appelle littéralement `pfx` — la
    recherche échouerait alors à tort sans passer par le chemin réel.
    """
    resolved = start_path.resolve()
    for parent in (resolved, *resolved.parents):
        if parent.name == "pfx" and (parent / "drive_c").is_dir():
            return parent
    return None


def _steam_root_candidates() -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".local/share/Steam",
        home / ".steam/steam",
        home / ".steam/root",
    ]
    return [c for c in candidates if c.is_dir()]


def find_proton_dir(prefix: Path) -> Path | None:
    """Retrouve le dossier d'installation de la version de Proton associée
    au préfixe `prefix` (ex: `compatdata/<appid>/pfx`), en lisant
    `compatdata/<appid>/config_info` (première ligne = nom de version, ex.
    "GE-Proton11-1") puis en cherchant un dossier Proton dont le fichier
    `version` correspond, sous compatibilitytools.d (Proton custom/GE) et
    steamapps/common (Proton officiel)."""
    appid_dir = prefix.parent
    config_info = appid_dir / "config_info"
    if not config_info.is_file():
        return None
    try:
        lines = config_info.read_text(encoding="utf-8", errors="ignore").splitlines()
        version_name = lines[0].strip() if lines else ""
    except OSError:
        return None
    if not version_name:
        return None

    search_roots: list[Path] = []
    for steam_root in _steam_root_candidates():
        search_roots.append(steam_root / "compatibilitytools.d")
        search_roots.append(steam_root / "steamapps" / "common")
    steamapps_dir = appid_dir.parent.parent  # <library>/steamapps
    if steamapps_dir.name == "steamapps":
        search_roots.append(steamapps_dir / "common")

    for root in search_roots:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            version_file = entry / "version"
            if not entry.is_dir() or not version_file.is_file():
                continue
            try:
                content = version_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if version_name in content:
                return entry
    return None


def find_proton_wine_bin(prefix: Path) -> Path | None:
    """Retrouve le binaire `wine` fourni par la version de Proton associée
    à `prefix`, plutôt qu'un `wine` système générique (souvent absent, ou
    d'une version incompatible avec le préfixe)."""
    proton_dir = find_proton_dir(prefix)
    if proton_dir is None:
        return None
    wine_bin = proton_dir / "files" / "bin" / "wine"
    return wine_bin if wine_bin.is_file() else None


def to_wine_path(path: Path) -> str:
    """Convertit un chemin Linux en chemin Windows tel qu'attendu par les
    validations internes (`System.Uri`) de certains outils .NET tournant
    sous Wine — ex: Divine.exe (LSLib) plante avec une exception "relative
    URI" sur un chemin absolu Unix passé tel quel en argument, ne le
    reconnaissant pas comme un chemin valide. `Z:` est par convention le
    lecteur que Wine mappe sur la racine `/` (comportement par défaut,
    présent dans tout préfixe standard) — cette conversion n'a de sens que
    sous Linux, pas sous Windows où le chemin natif suffit."""
    return "Z:" + str(path.resolve()).replace("/", "\\")


def default_env_appdata() -> str | None:
    """Retourne le chemin AppData local par défaut selon la plateforme,
    utilisé comme suggestion initiale dans l'assistant de configuration."""
    if is_windows():
        return os.environ.get("LOCALAPPDATA")
    # Sous Linux (Proton/Wine), l'AppData de BG3 se trouve généralement dans
    # le préfixe Wine/Proton, pas dans le HOME natif. On ne propose pas de
    # valeur par défaut fiable dans ce cas.
    return None
