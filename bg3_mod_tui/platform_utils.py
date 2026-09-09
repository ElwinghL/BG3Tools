"""Détection de plateforme et gestion des privilèges (admin Windows)."""

from __future__ import annotations

import os
import sys


def is_windows() -> bool:
    return sys.platform == "win32"


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


def default_env_appdata() -> str | None:
    """Retourne le chemin AppData local par défaut selon la plateforme,
    utilisé comme suggestion initiale dans l'assistant de configuration."""
    if is_windows():
        return os.environ.get("LOCALAPPDATA")
    # Sous Linux (Proton/Wine), l'AppData de BG3 se trouve généralement dans
    # le préfixe Wine/Proton, pas dans le HOME natif. On ne propose pas de
    # valeur par défaut fiable dans ce cas.
    return None
