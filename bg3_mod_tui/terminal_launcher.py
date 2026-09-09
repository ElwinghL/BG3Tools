"""Relance automatique du TUI dans un terminal dédié, avec une police
Nerd Font (MesloLGS NF) correctement configurée.

Le TUI ne peut pas imposer sa propre police au terminal qui l'affiche —
c'est une propriété exclusive de l'émulateur de terminal, pas de
l'application qui tourne dedans (voir README.md). La seule option est
donc de piloter nous-mêmes un émulateur de terminal *dédié*, avec un
profil qui lui impose la police voulue, puis de nous y relancer.

Un profil qui référence une police ne suffit pas si cette police n'est
pas installée sur la machine : les fichiers .ttf sont donc embarqués dans
le dépôt (`fonts/MesloLGS NF/`) et installés automatiquement pour
l'utilisateur courant (pas besoin de les récupérer/installer à la main
après un `git clone` sur une autre machine — voir `_ensure_font_installed`).

Comportement : au démarrage, `run()` (voir `__main__.py`) appelle
`relaunch_in_dedicated_terminal()` avant de lancer le TUI. Si un terminal
dédié a pu être ouvert, le process d'origine se termine immédiatement (le
nouveau process, lancé avec `BG3_MODTUI_DEDICATED_TERMINAL=1`, ne
retentera pas de relancer un terminal). Si aucun terminal n'a pu être
ouvert (émulateur absent, pas d'affichage disponible, ...), le TUI démarre
normalement dans le terminal actuel — jamais de blocage.

Désactivable via `BG3_MODTUI_NO_RELAUNCH=1` (utilisateur déjà dans le bon
terminal, environnement automatisé/CI, tests)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from bg3_mod_tui.platform_utils import is_windows

SENTINEL_ENV = "BG3_MODTUI_DEDICATED_TERMINAL"
DISABLE_ENV = "BG3_MODTUI_NO_RELAUNCH"

FONT_NAME = "MesloLGS NF"
KONSOLE_PROFILE_NAME = "BG3 Mod TUI"
WT_PROFILE_NAME = "BG3 Mod TUI"

# Fichiers .ttf embarqués dans le dépôt (voir fonts/README.md) — installés
# pour l'utilisateur courant si absents, pour qu'un profil de terminal qui
# référence FONT_NAME fonctionne réellement après un `git clone` sur une
# machine où la police n'est pas déjà installée.
FONTS_SOURCE_DIR = Path(__file__).resolve().parent.parent / "fonts" / "MesloLGS NF"
FONT_FILES = [
    "MesloLGS NF Regular.ttf",
    "MesloLGS NF Bold.ttf",
    "MesloLGS NF Italic.ttf",
    "MesloLGS NF Bold Italic.ttf",
]


def _linux_user_fonts_dir() -> Path:
    return Path.home() / ".local" / "share" / "fonts" / "BG3ModTUI"


def _windows_user_fonts_dir() -> Path | None:
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        return None
    return Path(localappdata) / "Microsoft" / "Windows" / "Fonts"


def _register_windows_font(display_name: str, path: Path) -> None:
    """Enregistre la police pour l'utilisateur courant (clé HKCU, pas
    besoin de droits admin), puis notifie les applications déjà ouvertes
    du changement (sans ça, une police tout juste installée n'est prise
    en compte qu'après reconnexion)."""
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"
        value_name = f"{display_name} (TrueType)"
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, str(path))

        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_FONTCHANGE = 0x001D
        ctypes.windll.user32.SendMessageW(HWND_BROADCAST, WM_FONTCHANGE, 0, 0)
    except Exception:
        pass


def _ensure_font_installed() -> None:
    """Installe MesloLGS NF (fichiers embarqués dans `fonts/MesloLGS NF/`)
    pour l'utilisateur courant si elle n'y est pas déjà — sans ça, un
    profil de terminal qui la référence s'ouvre avec la police système par
    défaut à la place. Ne fait jamais échouer l'appelant (best-effort :
    l'ouverture du terminal dédié reste tentée même si l'installation de
    la police échoue ou que les fichiers sources sont absents)."""
    if not FONTS_SOURCE_DIR.is_dir():
        return
    try:
        if is_windows():
            dest_dir = _windows_user_fonts_dir()
            if dest_dir is None:
                return
            if all((dest_dir / name).is_file() for name in FONT_FILES):
                return
            dest_dir.mkdir(parents=True, exist_ok=True)
            for name in FONT_FILES:
                src = FONTS_SOURCE_DIR / name
                if not src.is_file():
                    continue
                target = dest_dir / name
                if not target.is_file():
                    shutil.copy2(src, target)
                _register_windows_font(name[:-4], target)
        else:
            dest_dir = _linux_user_fonts_dir()
            if all((dest_dir / name).is_file() for name in FONT_FILES):
                return
            dest_dir.mkdir(parents=True, exist_ok=True)
            for name in FONT_FILES:
                src = FONTS_SOURCE_DIR / name
                if src.is_file():
                    shutil.copy2(src, dest_dir / name)
            fc_cache = shutil.which("fc-cache")
            if fc_cache:
                subprocess.run(
                    [fc_cache, "-f", str(dest_dir)], check=False, capture_output=True
                )
    except OSError:
        pass


def already_in_dedicated_terminal() -> bool:
    return os.environ.get(SENTINEL_ENV) == "1"


def relaunch_disabled() -> bool:
    return os.environ.get(DISABLE_ENV) == "1"


def _self_invocation() -> list[str]:
    """Reconstruit la commande relançant ce même TUI (même interpréteur,
    module `bg3_mod_tui`) — indépendant de la façon dont on a été lancé
    (`run.sh`, `python -m`, ou l'entry point installé)."""
    return [sys.executable, "-m", "bg3_mod_tui"]


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    env[SENTINEL_ENV] = "1"
    return env


def _has_display() -> bool:
    """Un émulateur de terminal est une application graphique : inutile
    d'essayer d'en ouvrir un sans serveur d'affichage (SSH sans X forward,
    CI headless, ...) — on continue alors dans le terminal actuel."""
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _ensure_konsole_profile() -> str:
    """Crée (ou met à jour) le profil Konsole dédié avec la police voulue,
    et retourne son nom. Konsole lit les profils sous
    `~/.local/share/konsole/*.profile` (format INI)."""
    profiles_dir = Path.home() / ".local" / "share" / "konsole"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profiles_dir / "bg3-mod-tui.profile"
    content = (
        "[Appearance]\n"
        f"Font={FONT_NAME},11,-1,5,50,0,0,0,0,0\n"
        "\n"
        "[General]\n"
        f"Name={KONSOLE_PROFILE_NAME}\n"
        "Parent=FALLBACK/\n"
    )
    profile_path.write_text(content, encoding="utf-8")
    return KONSOLE_PROFILE_NAME


def _try_linux_terminal(command: list[str], env: dict[str, str]) -> bool:
    if shutil.which("konsole"):
        profile_name = _ensure_konsole_profile()
        subprocess.Popen(
            ["konsole", "--profile", profile_name, "-e", *command],
            env=env,
            start_new_session=True,
        )
        return True

    # Repli générique : quelques émulateurs courants. Leur police se
    # configure normalement via un fichier de config global (dconf pour
    # gnome-terminal, kitty.conf, alacritty.toml, ...), pas via un flag de
    # ligne de commande simple pour tous — on ne garantit donc la police
    # que pour kitty/alacritty/xterm (flag direct), les autres s'ouvrent
    # avec leur police par défaut plutôt que de ne pas s'ouvrir du tout.
    fallbacks: list[list[str]] = [
        ["kitty", "-o", f"font_family={FONT_NAME}", *command],
        ["alacritty", "-o", f"font.normal.family={FONT_NAME}", "-e", *command],
        ["xterm", "-fa", FONT_NAME, "-e", *command],
        ["wezterm", "start", "--", *command],
        ["gnome-terminal", "--", *command],
        ["xfce4-terminal", "-e", subprocess.list2cmdline(command)],
        ["terminator", "-x", *command],
    ]
    for candidate in fallbacks:
        if shutil.which(candidate[0]):
            subprocess.Popen(candidate, env=env, start_new_session=True)
            return True
    return False


def _windows_terminal_settings_path() -> Path | None:
    localappdata = os.environ.get("LOCALAPPDATA")
    if not localappdata:
        return None
    packages_dir = Path(localappdata) / "Packages"
    if not packages_dir.is_dir():
        return None
    for entry in packages_dir.glob("Microsoft.WindowsTerminal_*"):
        candidate = entry / "LocalState" / "settings.json"
        if candidate.is_file():
            return candidate
    return None


def _ensure_windows_terminal_profile(command: list[str]) -> bool:
    """Ajoute/actualise le profil "BG3 Mod TUI" (police MesloLGS NF) dans
    `settings.json` de Windows Terminal. Retourne False si les settings
    sont introuvables (installation non standard) — on se contente alors
    de lancer `wt` sans profil dédié (police par défaut)."""
    settings_path = _windows_terminal_settings_path()
    if settings_path is None:
        return False

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False

    profiles = data.setdefault("profiles", {}).setdefault("list", [])
    existing = next((p for p in profiles if p.get("name") == WT_PROFILE_NAME), None)
    profile = existing if existing is not None else {"name": WT_PROFILE_NAME}
    profile["commandline"] = subprocess.list2cmdline(command)
    profile["font"] = {"face": FONT_NAME}
    if existing is None:
        profiles.append(profile)

    try:
        settings_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    except OSError:
        return False
    return True


def _try_windows_terminal(command: list[str], env: dict[str, str]) -> bool:
    wt_bin = shutil.which("wt") or shutil.which("wt.exe")
    if wt_bin:
        if _ensure_windows_terminal_profile(command):
            subprocess.Popen([wt_bin, "-p", WT_PROFILE_NAME], env=env)
        else:
            subprocess.Popen([wt_bin, *command], env=env)
        return True

    powershell_bin = shutil.which("powershell") or shutil.which("powershell.exe")
    if powershell_bin:
        subprocess.Popen(
            [powershell_bin, "-NoExit", "-Command", subprocess.list2cmdline(command)],
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        return True
    return False


def relaunch_in_dedicated_terminal() -> bool:
    """Tente d'ouvrir un terminal dédié (police MesloLGS NF quand
    l'émulateur le permet) et d'y relancer le TUI. Retourne True si un
    terminal a effectivement été lancé (l'appelant doit alors terminer le
    process courant sans lancer l'App Textual), False sinon (aucun
    émulateur trouvé, pas d'affichage disponible, ou lancement impossible
    — l'appelant doit alors continuer dans le terminal actuel)."""
    _ensure_font_installed()

    command = _self_invocation()
    env = _child_env()

    if is_windows():
        return _try_windows_terminal(command, env)

    if not _has_display():
        return False
    return _try_linux_terminal(command, env)
