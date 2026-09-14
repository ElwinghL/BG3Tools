"""Tests de `bg3_mod_tui.config` : résolution portable de la racine projet
(`resolve_project_root`, `_is_repo_checkout`) — mode "dépôt" (usage
principal, `bg3_mod_tui/` utilisé depuis l'intérieur du dépôt BG3Tools) vs
mode "package installé ailleurs" (`pip install .`/wheel, TODO.md 12a),
qui doit alors basculer vers un dossier de config XDG dédié.

Ne nécessite jamais d'installer réellement le package ailleurs : on injecte
directement un `base_dir` (répertoire simulant le parent de `bg3_mod_tui/`,
i.e. ce que donnerait `Path(__file__).resolve().parent.parent`) plutôt que
de dépendre du vrai `Path(__file__)` du module."""

from __future__ import annotations

from pathlib import Path

from bg3_mod_tui.config import (
    XDG_APP_DIR_NAME,
    _is_repo_checkout,
    _xdg_config_home,
    resolve_project_root,
)


def test_is_repo_checkout_detecte_le_marqueur_git(tmp_path):
    (tmp_path / ".git").mkdir()
    assert _is_repo_checkout(tmp_path) is True


def test_is_repo_checkout_detecte_le_dossier_tools(tmp_path):
    (tmp_path / "Tools").mkdir()
    assert _is_repo_checkout(tmp_path) is True


def test_is_repo_checkout_faux_si_aucun_marqueur(tmp_path):
    assert _is_repo_checkout(tmp_path) is False


def test_is_repo_checkout_git_peut_etre_un_fichier(tmp_path):
    # Cas d'un sous-module/worktree Git : `.git` est alors un fichier
    # (gitlink), pas un dossier — `.exists()` doit rester vrai.
    (tmp_path / ".git").write_text("gitdir: ../.git/worktrees/foo\n")
    assert _is_repo_checkout(tmp_path) is True


def test_resolve_project_root_mode_depot_retourne_base_dir(tmp_path):
    (tmp_path / ".git").mkdir()
    assert resolve_project_root(base_dir=tmp_path) == tmp_path


def test_resolve_project_root_mode_depot_via_dossier_tools(tmp_path):
    (tmp_path / "Tools").mkdir()
    assert resolve_project_root(base_dir=tmp_path) == tmp_path


def test_resolve_project_root_mode_package_bascule_vers_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdgconfig"))
    root = resolve_project_root(base_dir=tmp_path / "site-packages")
    assert root == tmp_path / "xdgconfig" / XDG_APP_DIR_NAME


def test_resolve_project_root_mode_package_sans_xdg_env_utilise_home(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home" / "user")
    root = resolve_project_root(base_dir=tmp_path / "site-packages")
    assert root == tmp_path / "home" / "user" / ".config" / XDG_APP_DIR_NAME


def test_xdg_config_home_respecte_la_variable_environnement(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "custom-xdg"))
    assert _xdg_config_home() == tmp_path / "custom-xdg"


def test_xdg_config_home_repli_sur_point_config_sous_home(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home" / "user")
    assert _xdg_config_home() == tmp_path / "home" / "user" / ".config"


def test_resolve_project_root_sans_base_dir_utilise_le_module(monkeypatch):
    # Sans argument, `resolve_project_root` dérive `base_dir` de
    # `Path(__file__)` du module `config` lui-même — dans ce dépôt de
    # test, ça reste la racine du dépôt BG3Tools (mode dépôt).
    import bg3_mod_tui.config as config_module

    expected = Path(config_module.__file__).resolve().parent.parent
    assert resolve_project_root() == expected
