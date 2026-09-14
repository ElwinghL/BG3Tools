"""Tests de `bg3_mod_tui.game_deploy.deploy_script_extender` : priorité de
`dist/` (notre build du fork ElwinghL/bg3se) sur la racine de
`Tools/BG3 Script Extender/` (ex: une release upstream Norbyte)."""

from __future__ import annotations

from pathlib import Path

from bg3_mod_tui.game_deploy import (
    SCRIPT_EXTENDER_DIR_NAME,
    SCRIPT_EXTENDER_DLL_TARGET_NAME,
    SCRIPT_EXTENDER_DIST_SUBDIR,
    deploy_script_extender,
)


def _make_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    tools_dir = tmp_path / "Tools"
    source_dir = tools_dir / SCRIPT_EXTENDER_DIR_NAME
    source_dir.mkdir(parents=True)
    game_bin_dir = tmp_path / "bin"
    game_bin_dir.mkdir()
    return tools_dir, source_dir, game_bin_dir


def test_deploy_script_extender_prefere_dist_a_la_racine(tmp_path):
    tools_dir, source_dir, game_bin_dir = _make_dirs(tmp_path)
    (source_dir / "DWrite.dll").write_bytes(b"upstream Norbyte")
    dist_dir = source_dir / SCRIPT_EXTENDER_DIST_SUBDIR
    dist_dir.mkdir()
    (dist_dir / "DWrite.dll").write_bytes(b"notre build ElwinghL/bg3se")

    deploy_script_extender(tools_dir, game_bin_dir, log=lambda _msg: None)

    deployed = game_bin_dir / SCRIPT_EXTENDER_DLL_TARGET_NAME
    assert deployed.read_bytes() == b"notre build ElwinghL/bg3se"


def test_deploy_script_extender_repli_racine_sans_dist(tmp_path):
    tools_dir, source_dir, game_bin_dir = _make_dirs(tmp_path)
    (source_dir / "DWrite.dll").write_bytes(b"upstream Norbyte")

    deploy_script_extender(tools_dir, game_bin_dir, log=lambda _msg: None)

    deployed = game_bin_dir / SCRIPT_EXTENDER_DLL_TARGET_NAME
    assert deployed.read_bytes() == b"upstream Norbyte"


def test_deploy_script_extender_dist_vide_retombe_sur_racine(tmp_path):
    # `dist/` existe (dossier créé) mais ne contient aucune .dll encore
    # (ex: build pas encore lancé) : ne doit pas être traité comme "aucune
    # DLL disponible", doit retomber sur la racine.
    tools_dir, source_dir, game_bin_dir = _make_dirs(tmp_path)
    (source_dir / "DWrite.dll").write_bytes(b"upstream Norbyte")
    (source_dir / SCRIPT_EXTENDER_DIST_SUBDIR).mkdir()

    deploy_script_extender(tools_dir, game_bin_dir, log=lambda _msg: None)

    deployed = game_bin_dir / SCRIPT_EXTENDER_DLL_TARGET_NAME
    assert deployed.read_bytes() == b"upstream Norbyte"


def test_deploy_script_extender_aucune_dll_ne_plante_pas(tmp_path):
    tools_dir, source_dir, game_bin_dir = _make_dirs(tmp_path)

    logs: list[str] = []
    deploy_script_extender(tools_dir, game_bin_dir, log=logs.append)

    assert not (game_bin_dir / SCRIPT_EXTENDER_DLL_TARGET_NAME).exists()
    assert any("aucune DLL" in line for line in logs)
