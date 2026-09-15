"""Tests pour bg3_mod_tui/terminal_launcher.py — relance du TUI dans un
terminal dédié (police + thème). Tout `subprocess.Popen`/`shutil.which` et
tout accès à `Path.home()`/variables d'environnement réel est mocké ou
redirigé vers `tmp_path` ; aucun terminal n'est réellement lancé."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bg3_mod_tui import terminal_launcher as tl


# ---------------------------------------------------------------------------
# _hex_to_rgb_csv
# ---------------------------------------------------------------------------


def test_hex_to_rgb_csv():
    assert tl._hex_to_rgb_csv("#C5A059") == "197,160,89"


def test_hex_to_rgb_csv_no_hash():
    assert tl._hex_to_rgb_csv("000000") == "0,0,0"


# ---------------------------------------------------------------------------
# fonts dirs
# ---------------------------------------------------------------------------


def test_linux_user_fonts_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert tl._linux_user_fonts_dir() == tmp_path / ".local" / "share" / "fonts" / "BG3ModTUI"


def test_windows_user_fonts_dir_no_env(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert tl._windows_user_fonts_dir() is None


def test_windows_user_fonts_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert tl._windows_user_fonts_dir() == tmp_path / "Microsoft" / "Windows" / "Fonts"


def test_register_windows_font_does_not_raise(tmp_path):
    # Sur Linux, `import winreg` échoue -> capturé par `except Exception`.
    tl._register_windows_font("MesloLGS NF Regular", tmp_path / "font.ttf")


# ---------------------------------------------------------------------------
# _ensure_font_installed
# ---------------------------------------------------------------------------


def _make_font_source(tmp_path):
    src = tmp_path / "fonts_src"
    src.mkdir()
    for name in tl.FONT_FILES:
        (src / name).write_bytes(b"fake-ttf")
    return src


def test_ensure_font_installed_no_source_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tl, "FONTS_SOURCE_DIR", tmp_path / "missing")
    # Ne doit rien faire ni lever.
    tl._ensure_font_installed()


def test_ensure_font_installed_linux_installs(tmp_path, monkeypatch):
    src = _make_font_source(tmp_path)
    dest = tmp_path / "dest_fonts"
    monkeypatch.setattr(tl, "FONTS_SOURCE_DIR", src)
    monkeypatch.setattr(tl, "_linux_user_fonts_dir", lambda: dest)
    monkeypatch.setattr(tl, "is_windows", lambda: False)
    with patch.object(tl.shutil, "which", return_value=None):
        tl._ensure_font_installed()
    for name in tl.FONT_FILES:
        assert (dest / name).is_file()


def test_ensure_font_installed_linux_already_present(tmp_path, monkeypatch):
    src = _make_font_source(tmp_path)
    dest = tmp_path / "dest_fonts"
    dest.mkdir()
    for name in tl.FONT_FILES:
        (dest / name).write_bytes(b"already")
    monkeypatch.setattr(tl, "FONTS_SOURCE_DIR", src)
    monkeypatch.setattr(tl, "_linux_user_fonts_dir", lambda: dest)
    monkeypatch.setattr(tl, "is_windows", lambda: False)
    with patch.object(tl.shutil, "which") as which:
        tl._ensure_font_installed()
    which.assert_not_called()


def test_ensure_font_installed_linux_runs_fc_cache(tmp_path, monkeypatch):
    src = _make_font_source(tmp_path)
    dest = tmp_path / "dest_fonts"
    monkeypatch.setattr(tl, "FONTS_SOURCE_DIR", src)
    monkeypatch.setattr(tl, "_linux_user_fonts_dir", lambda: dest)
    monkeypatch.setattr(tl, "is_windows", lambda: False)
    with (
        patch.object(tl.shutil, "which", return_value="/usr/bin/fc-cache"),
        patch.object(tl.subprocess, "run") as run,
    ):
        tl._ensure_font_installed()
    run.assert_called_once()


def test_ensure_font_installed_oserror_swallowed(tmp_path, monkeypatch):
    src = _make_font_source(tmp_path)
    monkeypatch.setattr(tl, "FONTS_SOURCE_DIR", src)
    monkeypatch.setattr(tl, "is_windows", lambda: False)
    monkeypatch.setattr(tl, "_linux_user_fonts_dir", MagicMock(side_effect=OSError("nope")))
    tl._ensure_font_installed()  # ne doit pas lever


def test_ensure_font_installed_windows_no_dest(tmp_path, monkeypatch):
    src = _make_font_source(tmp_path)
    monkeypatch.setattr(tl, "FONTS_SOURCE_DIR", src)
    monkeypatch.setattr(tl, "is_windows", lambda: True)
    monkeypatch.setattr(tl, "_windows_user_fonts_dir", lambda: None)
    tl._ensure_font_installed()


def test_ensure_font_installed_windows_installs(tmp_path, monkeypatch):
    src = _make_font_source(tmp_path)
    dest = tmp_path / "win_fonts"
    monkeypatch.setattr(tl, "FONTS_SOURCE_DIR", src)
    monkeypatch.setattr(tl, "is_windows", lambda: True)
    monkeypatch.setattr(tl, "_windows_user_fonts_dir", lambda: dest)
    with patch.object(tl, "_register_windows_font") as register:
        tl._ensure_font_installed()
    for name in tl.FONT_FILES:
        assert (dest / name).is_file()
    assert register.call_count == len(tl.FONT_FILES)


def test_ensure_font_installed_windows_already_present(tmp_path, monkeypatch):
    src = _make_font_source(tmp_path)
    dest = tmp_path / "win_fonts"
    dest.mkdir()
    for name in tl.FONT_FILES:
        (dest / name).write_bytes(b"x")
    monkeypatch.setattr(tl, "FONTS_SOURCE_DIR", src)
    monkeypatch.setattr(tl, "is_windows", lambda: True)
    monkeypatch.setattr(tl, "_windows_user_fonts_dir", lambda: dest)
    with patch.object(tl, "_register_windows_font") as register:
        tl._ensure_font_installed()
    register.assert_not_called()


# ---------------------------------------------------------------------------
# sentinel env helpers
# ---------------------------------------------------------------------------


def test_already_in_dedicated_terminal(monkeypatch):
    monkeypatch.delenv(tl.SENTINEL_ENV, raising=False)
    assert tl.already_in_dedicated_terminal() is False
    monkeypatch.setenv(tl.SENTINEL_ENV, "1")
    assert tl.already_in_dedicated_terminal() is True


def test_relaunch_disabled(monkeypatch):
    monkeypatch.delenv(tl.DISABLE_ENV, raising=False)
    assert tl.relaunch_disabled() is False
    monkeypatch.setenv(tl.DISABLE_ENV, "1")
    assert tl.relaunch_disabled() is True


def test_self_invocation():
    assert tl._self_invocation() == [sys.executable, "-m", "bg3_mod_tui"]


def test_child_env(monkeypatch):
    monkeypatch.delenv(tl.SENTINEL_ENV, raising=False)
    env = tl._child_env()
    assert env[tl.SENTINEL_ENV] == "1"


def test_has_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert tl._has_display() is False
    monkeypatch.setenv("DISPLAY", ":0")
    assert tl._has_display() is True


def test_has_display_wayland(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert tl._has_display() is True


# ---------------------------------------------------------------------------
# Konsole colorscheme / profile
# ---------------------------------------------------------------------------


def test_ensure_konsole_colorscheme_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    name = tl._ensure_konsole_colorscheme()
    assert name == tl.KONSOLE_COLORSCHEME_NAME
    scheme_path = tmp_path / ".local" / "share" / "konsole" / "bg3-mod-tui.colorscheme"
    content = scheme_path.read_text(encoding="utf-8")
    assert "[Background]" in content
    assert f"Description={tl.KONSOLE_COLORSCHEME_NAME}" in content


def test_ensure_konsole_profile_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    name = tl._ensure_konsole_profile()
    assert name == tl.KONSOLE_PROFILE_NAME
    profile_path = tmp_path / ".local" / "share" / "konsole" / "bg3-mod-tui.profile"
    content = profile_path.read_text(encoding="utf-8")
    assert tl.FONT_NAME in content
    assert f"Name={tl.KONSOLE_PROFILE_NAME}" in content


# ---------------------------------------------------------------------------
# _hold_on_failure
# ---------------------------------------------------------------------------


def test_hold_on_failure_wraps_command():
    wrapped = tl._hold_on_failure(["python3", "-m", "bg3_mod_tui"])
    assert wrapped[0] == "bash"
    assert wrapped[1] == "-c"
    assert "python3 -m bg3_mod_tui" in wrapped[2]
    assert "appuyez sur Entrée" in wrapped[2]


# ---------------------------------------------------------------------------
# _try_linux_terminal
# ---------------------------------------------------------------------------


def test_try_linux_terminal_konsole(monkeypatch):
    monkeypatch.setattr(tl, "_ensure_konsole_profile", lambda: "Profile")
    with (
        patch.object(
            tl.shutil,
            "which",
            side_effect=lambda name: "/usr/bin/konsole" if name == "konsole" else None,
        ),
        patch.object(tl.subprocess, "Popen") as popen,
    ):
        result = tl._try_linux_terminal(["cmd"], {"E": "1"})
    assert result is True
    popen.assert_called_once()
    args = popen.call_args.args[0]
    assert args[0] == "konsole"


def test_try_linux_terminal_fallback_kitty(monkeypatch):
    with (
        patch.object(
            tl.shutil,
            "which",
            side_effect=lambda name: "/usr/bin/kitty" if name == "kitty" else None,
        ),
        patch.object(tl.subprocess, "Popen") as popen,
    ):
        result = tl._try_linux_terminal(["cmd"], {})
    assert result is True
    assert popen.call_args.args[0][0] == "kitty"


def test_try_linux_terminal_no_emulator(monkeypatch):
    with patch.object(tl.shutil, "which", return_value=None):
        result = tl._try_linux_terminal(["cmd"], {})
    assert result is False


# ---------------------------------------------------------------------------
# Windows Terminal helpers
# ---------------------------------------------------------------------------


def test_windows_terminal_settings_path_no_env(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert tl._windows_terminal_settings_path() is None


def test_windows_terminal_settings_path_no_packages_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert tl._windows_terminal_settings_path() is None


def test_windows_terminal_settings_path_found(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    packages = tmp_path / "Packages"
    pkg_dir = packages / "Microsoft.WindowsTerminal_8wekyb3d8bbwe"
    state_dir = pkg_dir / "LocalState"
    state_dir.mkdir(parents=True)
    settings = state_dir / "settings.json"
    settings.write_text("{}", encoding="utf-8")
    assert tl._windows_terminal_settings_path() == settings


def test_windows_terminal_settings_path_no_settings_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    packages = tmp_path / "Packages"
    (packages / "Microsoft.WindowsTerminal_8wekyb3d8bbwe" / "LocalState").mkdir(parents=True)
    assert tl._windows_terminal_settings_path() is None


def test_windows_terminal_color_scheme_keys():
    scheme = tl._windows_terminal_color_scheme()
    assert scheme["name"] == tl.KONSOLE_COLORSCHEME_NAME
    assert "background" in scheme and "brightWhite" in scheme


def test_ensure_windows_terminal_profile_no_settings(monkeypatch):
    monkeypatch.setattr(tl, "_windows_terminal_settings_path", lambda: None)
    assert tl._ensure_windows_terminal_profile(["cmd"]) is False


def test_ensure_windows_terminal_profile_bad_json(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(tl, "_windows_terminal_settings_path", lambda: settings)
    assert tl._ensure_windows_terminal_profile(["cmd"]) is False


def test_ensure_windows_terminal_profile_creates_new(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(tl, "_windows_terminal_settings_path", lambda: settings)

    result = tl._ensure_windows_terminal_profile(["python", "-m", "bg3_mod_tui"])
    assert result is True

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert any(s["name"] == tl.KONSOLE_COLORSCHEME_NAME for s in data["schemes"])
    profiles = data["profiles"]["list"]
    assert any(p["name"] == tl.WT_PROFILE_NAME for p in profiles)


def test_ensure_windows_terminal_profile_updates_existing(tmp_path, monkeypatch):
    existing_data = {
        "schemes": [{"name": tl.KONSOLE_COLORSCHEME_NAME, "background": "#000000"}],
        "profiles": {"list": [{"name": tl.WT_PROFILE_NAME, "commandline": "old"}]},
    }
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(existing_data), encoding="utf-8")
    monkeypatch.setattr(tl, "_windows_terminal_settings_path", lambda: settings)

    result = tl._ensure_windows_terminal_profile(["python", "-m", "bg3_mod_tui"])
    assert result is True

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert len(data["schemes"]) == 1
    assert len(data["profiles"]["list"]) == 1
    assert data["profiles"]["list"][0]["commandline"] == "python -m bg3_mod_tui"


def test_ensure_windows_terminal_profile_write_oserror(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr(tl, "_windows_terminal_settings_path", lambda: settings)
    with patch.object(Path, "write_text", side_effect=OSError("disk full")):
        assert tl._ensure_windows_terminal_profile(["cmd"]) is False


def test_try_windows_terminal_wt_with_profile(monkeypatch):
    monkeypatch.setattr(tl, "_ensure_windows_terminal_profile", lambda cmd: True)
    with (
        patch.object(
            tl.shutil, "which", side_effect=lambda name: "wt.exe" if name == "wt" else None
        ),
        patch.object(tl.subprocess, "Popen") as popen,
    ):
        result = tl._try_windows_terminal(["cmd"], {})
    assert result is True
    popen.assert_called_once_with(["wt.exe", "-p", tl.WT_PROFILE_NAME], env={})


def test_try_windows_terminal_wt_without_profile(monkeypatch):
    monkeypatch.setattr(tl, "_ensure_windows_terminal_profile", lambda cmd: False)
    with (
        patch.object(
            tl.shutil, "which", side_effect=lambda name: "wt.exe" if name == "wt" else None
        ),
        patch.object(tl.subprocess, "Popen") as popen,
    ):
        result = tl._try_windows_terminal(["cmd"], {})
    assert result is True
    popen.assert_called_once_with(["wt.exe", "cmd"], env={})


def test_try_windows_terminal_powershell_fallback(monkeypatch):
    with (
        patch.object(
            tl.shutil,
            "which",
            side_effect=lambda name: "powershell.exe" if name == "powershell" else None,
        ),
        patch.object(tl.subprocess, "Popen") as popen,
        patch.object(tl.subprocess, "CREATE_NEW_CONSOLE", 0x10, create=True),
    ):
        result = tl._try_windows_terminal(["cmd"], {})
    assert result is True
    popen.assert_called_once()


def test_try_windows_terminal_nothing_found(monkeypatch):
    with patch.object(tl.shutil, "which", return_value=None):
        result = tl._try_windows_terminal(["cmd"], {})
    assert result is False


# ---------------------------------------------------------------------------
# relaunch_in_dedicated_terminal
# ---------------------------------------------------------------------------


def test_relaunch_in_dedicated_terminal_windows(monkeypatch):
    monkeypatch.setattr(tl, "_ensure_font_installed", lambda: None)
    monkeypatch.setattr(tl, "is_windows", lambda: True)
    monkeypatch.setattr(tl, "_try_windows_terminal", lambda cmd, env: True)
    assert tl.relaunch_in_dedicated_terminal() is True


def test_relaunch_in_dedicated_terminal_linux_no_display(monkeypatch):
    monkeypatch.setattr(tl, "_ensure_font_installed", lambda: None)
    monkeypatch.setattr(tl, "is_windows", lambda: False)
    monkeypatch.setattr(tl, "_has_display", lambda: False)
    assert tl.relaunch_in_dedicated_terminal() is False


def test_relaunch_in_dedicated_terminal_linux_with_display(monkeypatch):
    monkeypatch.setattr(tl, "_ensure_font_installed", lambda: None)
    monkeypatch.setattr(tl, "is_windows", lambda: False)
    monkeypatch.setattr(tl, "_has_display", lambda: True)
    monkeypatch.setattr(tl, "_try_linux_terminal", lambda cmd, env: True)
    assert tl.relaunch_in_dedicated_terminal() is True
