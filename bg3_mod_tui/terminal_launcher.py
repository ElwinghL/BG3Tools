"""Relance automatique du TUI dans un terminal dédié, avec une police
Nerd Font (MesloLGS NF) et le thème de couleurs BG3 (voir `theme.py`)
correctement configurés.

Le TUI ne peut pas imposer sa propre police ni ses propres couleurs au
terminal qui l'affiche — ce sont des propriétés exclusives de
l'émulateur de terminal, pas de l'application qui tourne dedans (voir
README.md). La seule option est donc de piloter nous-mêmes un émulateur
de terminal *dédié*, avec un profil qui lui impose police et couleurs,
puis de nous y relancer. Le profil (et son schéma de couleurs) est
régénéré à chaque tentative de relance, pas seulement à la première
création — s'il change côté `theme.py`, le profil suit au prochain
démarrage sans étape manuelle.

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
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from bg3_mod_tui.platform_utils import is_windows
from bg3_mod_tui.theme import BG3_THEME

SENTINEL_ENV = "BG3_MODTUI_DEDICATED_TERMINAL"
DISABLE_ENV = "BG3_MODTUI_NO_RELAUNCH"

FONT_NAME = "MesloLGS NF"
KONSOLE_PROFILE_NAME = "BG3 Mod TUI"
KONSOLE_COLORSCHEME_NAME = "BG3 Mod TUI"
WT_PROFILE_NAME = "BG3 Mod TUI"


def _hex_to_rgb_csv(hex_color: str) -> str:
    """`"#RRGGBB"` -> `"R,G,B"` (format attendu par les fichiers
    `.colorscheme` de Konsole)."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"{r},{g},{b}"

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


def _ensure_konsole_colorscheme() -> str:
    """Crée (ou met à jour) le schéma de couleurs Konsole dédié, aux
    teintes du thème BG3 (voir `theme.py`), et retourne son nom. Konsole
    lit les schémas sous `~/.local/share/konsole/*.colorscheme` (format
    INI, couleurs en `R,G,B` décimal — pas en hexadécimal)."""
    rgb = _hex_to_rgb_csv
    schemes_dir = Path.home() / ".local" / "share" / "konsole"
    schemes_dir.mkdir(parents=True, exist_ok=True)
    scheme_path = schemes_dir / "bg3-mod-tui.colorscheme"

    background = BG3_THEME.background
    foreground = BG3_THEME.foreground
    # Correspondance ANSI 0-7 avec les couleurs du thème — palette
    # restreinte (pas de vert franc ni de vrai cyan dans la source), donc
    # certains emplacements réutilisent la teinte la plus proche
    # disponible (bronze/or/sarcelle) plutôt qu'une couleur hors thème.
    ansi = {
        0: BG3_THEME.surface,  # noir -> panneaux (fond sombre)
        1: BG3_THEME.error,  # rouge
        2: BG3_THEME.secondary,  # vert -> sarcelle (pas de vert dans la palette)
        3: BG3_THEME.primary,  # jaune -> or
        4: BG3_THEME.secondary,  # bleu -> sarcelle
        5: BG3_THEME.accent,  # magenta -> bronze
        6: BG3_THEME.secondary,  # cyan -> sarcelle
        7: foreground,  # blanc
    }
    lines = [
        "[Background]",
        f"Color={rgb(background)}",
        "",
        "[BackgroundIntense]",
        f"Color={rgb(background)}",
        "",
        "[Foreground]",
        f"Color={rgb(foreground)}",
        "",
        "[ForegroundIntense]",
        f"Color={rgb(foreground)}",
        "",
    ]
    for index, hex_color in ansi.items():
        lines += [f"[Color{index}]", f"Color={rgb(hex_color)}", ""]
        lines += [f"[Color{index}Intense]", f"Color={rgb(hex_color)}", ""]
    lines += [
        "[General]",
        f"Description={KONSOLE_COLORSCHEME_NAME}",
        "Opacity=1",
        "Wallpaper=",
    ]
    scheme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return KONSOLE_COLORSCHEME_NAME


def _ensure_konsole_profile() -> str:
    """Crée (ou met à jour) le profil Konsole dédié avec la police et le
    thème de couleurs BG3 (voir `_ensure_konsole_colorscheme`), et
    retourne son nom. Konsole lit les profils sous
    `~/.local/share/konsole/*.profile` (format INI)."""
    colorscheme_name = _ensure_konsole_colorscheme()

    profiles_dir = Path.home() / ".local" / "share" / "konsole"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profiles_dir / "bg3-mod-tui.profile"
    content = (
        "[Appearance]\n"
        f"Font={FONT_NAME},11,-1,5,50,0,0,0,0,0\n"
        f"ColorScheme={colorscheme_name}\n"
        "\n"
        "[General]\n"
        f"Name={KONSOLE_PROFILE_NAME}\n"
        "Parent=FALLBACK/\n"
    )
    profile_path.write_text(content, encoding="utf-8")
    return KONSOLE_PROFILE_NAME


def _hold_on_failure(command: list[str]) -> list[str]:
    """Enveloppe `command` pour que la fenêtre de terminal dédiée reste
    ouverte si le TUI se termine avec un code de sortie non nul (crash),
    au lieu de se fermer immédiatement et de masquer toute trace de
    l'erreur. Ne change rien au comportement en cas de sortie normale
    (code 0) — la fenêtre se ferme comme avant."""
    script = (
        f"{shlex.join(command)}; ec=$?; "
        f"if [ $ec -ne 0 ]; then echo; "
        f"echo 'Le programme a quitté avec le code '$ec' — appuyez sur Entrée pour fermer.'; "
        f"read _; fi"
    )
    return ["bash", "-c", script]


def _try_linux_terminal(command: list[str], env: dict[str, str]) -> bool:
    wrapped = _hold_on_failure(command)

    if shutil.which("konsole"):
        profile_name = _ensure_konsole_profile()
        subprocess.Popen(
            ["konsole", "--profile", profile_name, "-e", *wrapped],
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
        ["kitty", "-o", f"font_family={FONT_NAME}", *wrapped],
        ["alacritty", "-o", f"font.normal.family={FONT_NAME}", "-e", *wrapped],
        ["xterm", "-fa", FONT_NAME, "-e", *wrapped],
        ["wezterm", "start", "--", *wrapped],
        ["gnome-terminal", "--", *wrapped],
        ["xfce4-terminal", "-e", subprocess.list2cmdline(wrapped)],
        ["terminator", "-x", *wrapped],
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


def _windows_terminal_color_scheme() -> dict[str, str]:
    """Schéma de couleurs Windows Terminal aux teintes du thème BG3 (voir
    `theme.py`). Même correspondance ANSI que `_ensure_konsole_colorscheme`
    (palette source sans vert ni cyan francs)."""
    return {
        "name": KONSOLE_COLORSCHEME_NAME,
        "background": BG3_THEME.background,
        "foreground": BG3_THEME.foreground,
        "cursorColor": BG3_THEME.foreground,
        "selectionBackground": BG3_THEME.accent,
        "black": BG3_THEME.surface,
        "brightBlack": BG3_THEME.panel,
        "red": BG3_THEME.error,
        "brightRed": BG3_THEME.error,
        "green": BG3_THEME.secondary,
        "brightGreen": BG3_THEME.secondary,
        "yellow": BG3_THEME.primary,
        "brightYellow": BG3_THEME.primary,
        "blue": BG3_THEME.secondary,
        "brightBlue": BG3_THEME.secondary,
        "purple": BG3_THEME.accent,
        "brightPurple": BG3_THEME.accent,
        "cyan": BG3_THEME.secondary,
        "brightCyan": BG3_THEME.secondary,
        "white": BG3_THEME.foreground,
        "brightWhite": BG3_THEME.foreground,
    }


def _ensure_windows_terminal_profile(command: list[str]) -> bool:
    """Ajoute/actualise le profil "BG3 Mod TUI" (police MesloLGS NF, thème
    de couleurs BG3) dans `settings.json` de Windows Terminal. Retourne
    False si les settings sont introuvables (installation non standard)
    — on se contente alors de lancer `wt` sans profil dédié (police et
    couleurs par défaut)."""
    settings_path = _windows_terminal_settings_path()
    if settings_path is None:
        return False

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False

    schemes = data.setdefault("schemes", [])
    scheme = _windows_terminal_color_scheme()
    existing_scheme_index = next(
        (i for i, s in enumerate(schemes) if s.get("name") == scheme["name"]), None
    )
    if existing_scheme_index is None:
        schemes.append(scheme)
    else:
        schemes[existing_scheme_index] = scheme

    profiles = data.setdefault("profiles", {}).setdefault("list", [])
    existing = next((p for p in profiles if p.get("name") == WT_PROFILE_NAME), None)
    profile = existing if existing is not None else {"name": WT_PROFILE_NAME}
    profile["commandline"] = subprocess.list2cmdline(command)
    profile["font"] = {"face": FONT_NAME}
    profile["colorScheme"] = scheme["name"]
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


def open_in_terminal(command: list[str]) -> bool:
    """Ouvre un terminal externe (même détection multi-émulateur que
    `relaunch_in_dedicated_terminal` : Konsole/kitty/alacritty/xterm/...
    sous Linux, Windows Terminal/PowerShell sous Windows) et y exécute
    `command`, sans le profil/police/thème dédiés ni la relance du TUI
    (utilisé par un outil ponctuel, ex. le suivi des logs Script Extender —
    voir `script_extender_console.py` — pas par le TUI lui-même).

    Retourne True si un terminal a effectivement pu être ouvert, False
    sinon (aucun émulateur trouvé, ou pas d'affichage disponible sous
    Linux) — l'appelant doit alors se rabattre sur un autre moyen d'informer
    l'utilisateur (ex. un message dans le TUI), jamais bloquer ni planter."""
    env = os.environ.copy()
    if is_windows():
        return _try_windows_terminal(command, env)
    if not _has_display():
        return False
    return _try_linux_terminal(command, env)


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
