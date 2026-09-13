"""Tests de la sous-tâche 11a : localisation des logs BG3SE et
construction de la commande de suivi ("tail") lancée dans un terminal
externe. Ne teste pas l'ouverture réelle d'un terminal (dépend de
l'environnement graphique/des émulateurs installés, hors de portée ici) ni
un vrai jeu lancé — uniquement la logique pure (chemins, commande)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bg3_mod_tui import script_extender_console as sec


def _make_proton_tree(tmp_path: Path, appid: str = "1086940", user: str = "steamuser") -> Path:
    """Construit une arborescence factice `.../compatdata/<appid>/pfx/...`
    et retourne le chemin d'AppData BG3 factice sous ce préfixe (comme
    `Config.appdata_path`)."""
    pfx = tmp_path / "compatdata" / appid / "pfx"
    appdata = pfx / "drive_c" / "users" / user / "AppData" / "Local" / "Larian Studios" / "Baldur's Gate 3"
    appdata.mkdir(parents=True)
    return appdata


def test_find_proton_user_dir_locates_user_root(tmp_path: Path) -> None:
    appdata = _make_proton_tree(tmp_path, user="steamuser")
    user_dir = sec.find_proton_user_dir(appdata)
    assert user_dir is not None
    assert user_dir.name == "steamuser"
    assert user_dir.parent.name == "users"


def test_find_proton_user_dir_none_without_proton_prefix(tmp_path: Path) -> None:
    # Aucun dossier "pfx" dans l'arborescence : pas un préfixe Proton.
    appdata = tmp_path / "AppData" / "Local" / "Larian Studios" / "Baldur's Gate 3"
    appdata.mkdir(parents=True)
    assert sec.find_proton_user_dir(appdata) is None


def test_find_osiris_log_dir_under_proton(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sec, "is_windows", lambda: False)
    appdata = _make_proton_tree(tmp_path, user="myuser")
    log_dir = sec.find_osiris_log_dir(appdata)
    assert log_dir is not None
    assert log_dir == appdata.parents[3] / "My Documents" / "OsirisLogs"
    # Pas dérivé de l'AppData Local elle-même (dossier spécial distinct).
    assert "AppData" not in log_dir.parts


def test_find_osiris_log_dir_none_when_prefix_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sec, "is_windows", lambda: False)
    appdata = tmp_path / "AppData" / "Local" / "Larian Studios" / "Baldur's Gate 3"
    appdata.mkdir(parents=True)
    assert sec.find_osiris_log_dir(appdata) is None


def test_find_osiris_log_dir_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sec, "is_windows", lambda: True)
    log_dir = sec.find_osiris_log_dir(Path("unused"))
    assert log_dir == Path.home() / "Documents" / "OsirisLogs"


def test_build_tail_command_linux_waits_and_tails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sec, "is_windows", lambda: False)
    log_dir = Path("/tmp/some dir/OsirisLogs")
    command = sec.build_tail_command(log_dir)
    assert command[0] == "bash"
    assert command[1] == "-c"
    script = command[2]
    assert "tail -n +1 -F" in script
    assert "*.log" in script
    # Chemin avec espace correctement échappé pour le shell.
    assert "'/tmp/some dir/OsirisLogs'" in script
    assert "EnableLogging" in script


def test_build_tail_command_windows_uses_powershell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sec, "is_windows", lambda: True)
    log_dir = Path(r"C:\Users\me\Documents\OsirisLogs")
    command = sec.build_tail_command(log_dir)
    assert command[0] == "powershell"
    script = command[-1]
    assert "Get-Content" in script
    assert "-Wait" in script
    assert "EnableLogging" in script
