"""Tests pour bg3_mod_tui.nmcm_bridges.

Pas de vrai .pak/Divine.exe impliqué : ces tests vérifient uniquement la
découverte des .pak sous Tools/nmcm_patches/*/dist/ et la logique de
liaison (hardlink, idempotence, repli symlink via link_or_symlink)."""

from __future__ import annotations

from pathlib import Path

from bg3_mod_tui import nmcm_bridges as nb


def _make_bridge(tools_dir: Path, name: str, content: bytes = b"fake-pak") -> Path:
    dist_dir = tools_dir / nb.NMCM_PATCHES_DIRNAME / name / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    pak = dist_dir / f"{name}_NMCM_Bridge.pak"
    pak.write_bytes(content)
    return pak


def test_discover_bridge_paks_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert nb.discover_bridge_paks(tmp_path) == []


def test_discover_bridge_paks_finds_all_dist_paks(tmp_path: Path) -> None:
    pak1 = _make_bridge(tmp_path, "AbsoluteDefeat")
    pak2 = _make_bridge(tmp_path, "VisibleShields")

    result = nb.discover_bridge_paks(tmp_path)

    assert result == sorted([pak1, pak2])


def test_discover_bridge_paks_picks_up_new_bridge_without_code_change(tmp_path: Path) -> None:
    # Simule un futur pont ajouté sous un nom jamais vu par ce module :
    # la découverte reste purement filesystem, aucune liste à maintenir.
    _make_bridge(tmp_path, "AbsoluteDefeat")
    future_pak = _make_bridge(tmp_path, "SomeFutureBridge")

    result = nb.discover_bridge_paks(tmp_path)

    assert future_pak in result


def test_discover_bridge_paks_ignores_non_pak_files(tmp_path: Path) -> None:
    dist_dir = tmp_path / nb.NMCM_PATCHES_DIRNAME / "AbsoluteDefeat" / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / "README.md").write_text("not a pak")

    assert nb.discover_bridge_paks(tmp_path) == []


def test_deploy_nmcm_bridges_links_each_pak(tmp_path: Path) -> None:
    tools_dir = tmp_path / "Tools"
    mods_dir = tmp_path / "Mods"
    pak1 = _make_bridge(tools_dir, "AbsoluteDefeat")
    pak2 = _make_bridge(tools_dir, "VisibleShields")

    logs: list[str] = []
    linked = nb.deploy_nmcm_bridges(mods_dir, tools_dir, log=logs.append)

    assert set(linked) == {pak1, pak2}
    for pak in (pak1, pak2):
        target = mods_dir / pak.name
        assert target.is_file()
        assert target.stat().st_ino == pak.stat().st_ino
    assert any("2 pont(s)" in line for line in logs)


def test_deploy_nmcm_bridges_no_bridges_found(tmp_path: Path) -> None:
    tools_dir = tmp_path / "Tools"
    mods_dir = tmp_path / "Mods"

    logs: list[str] = []
    linked = nb.deploy_nmcm_bridges(mods_dir, tools_dir, log=logs.append)

    assert linked == []
    assert not mods_dir.exists()
    assert any("Aucun pont NMCM" in line for line in logs)


def test_deploy_nmcm_bridges_is_idempotent(tmp_path: Path) -> None:
    tools_dir = tmp_path / "Tools"
    mods_dir = tmp_path / "Mods"
    _make_bridge(tools_dir, "AbsoluteDefeat")

    nb.deploy_nmcm_bridges(mods_dir, tools_dir)
    logs: list[str] = []
    linked_second = nb.deploy_nmcm_bridges(mods_dir, tools_dir, log=logs.append)

    assert linked_second == []
    assert any("déjà relié" in line for line in logs)


def test_deploy_nmcm_bridges_replaces_stale_target(tmp_path: Path) -> None:
    tools_dir = tmp_path / "Tools"
    mods_dir = tmp_path / "Mods"
    mods_dir.mkdir()
    pak = _make_bridge(tools_dir, "AbsoluteDefeat")

    stale_target = mods_dir / pak.name
    stale_target.write_bytes(b"stale-unrelated-content")

    linked = nb.deploy_nmcm_bridges(mods_dir, tools_dir)

    assert linked == [pak]
    assert stale_target.stat().st_ino == pak.stat().st_ino
