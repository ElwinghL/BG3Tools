"""Tests pour bg3_mod_tui.linking."""

from __future__ import annotations

import errno

import pytest

from bg3_mod_tui import config as config_module
from bg3_mod_tui import linking
from bg3_mod_tui.config import ModToolsConfig


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Un ModToolsConfig dont `managed_dir` pointe sous tmp_path (au lieu
    du vrai `CONFIG_PATH` du projet)."""
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "bg3modtools.toml")
    install_dir = tmp_path / "install"
    appdata_dir = tmp_path / "appdata"
    install_dir.mkdir()
    appdata_dir.mkdir()
    return ModToolsConfig(bg3_install_dir=str(install_dir), bg3_appdata_dir=str(appdata_dir))


def test_linking_report_add():
    report = linking.LinkingReport(steps=[])
    report.add("étape 1")
    assert report.steps == ["étape 1"]


def test_create_symlink_creates_new(tmp_path):
    target = tmp_path / "target_dir"
    target.mkdir()
    link_path = tmp_path / "sub" / "link"
    linking._create_symlink(link_path, target, target_is_dir=True)
    assert link_path.is_symlink()
    assert link_path.resolve() == target.resolve()


def test_create_symlink_already_correct_is_noop(tmp_path):
    target = tmp_path / "target_dir"
    target.mkdir()
    link_path = tmp_path / "link"
    link_path.symlink_to(target, target_is_directory=True)
    linking._create_symlink(link_path, target, target_is_dir=True)  # ne lève pas


def test_create_symlink_existing_wrong_thing_raises(tmp_path):
    target = tmp_path / "target_dir"
    target.mkdir()
    link_path = tmp_path / "link"
    link_path.mkdir()
    with pytest.raises(linking.LinkingError):
        linking._create_symlink(link_path, target, target_is_dir=True)


def test_create_symlink_oserror_windows_admin_message(tmp_path, monkeypatch):
    target = tmp_path / "target_dir"
    target.mkdir()
    link_path = tmp_path / "link"

    def fake_symlink(*args, **kwargs):
        raise OSError(errno.EPERM, "denied")

    monkeypatch.setattr(linking.os, "symlink", fake_symlink)
    monkeypatch.setattr(linking, "is_windows", lambda: True)
    monkeypatch.setattr(linking, "can_create_links_without_admin", lambda: False)
    with pytest.raises(linking.LinkingError, match="administrateur"):
        linking._create_symlink(link_path, target, target_is_dir=True)


def test_create_symlink_oserror_generic_message(tmp_path, monkeypatch):
    target = tmp_path / "target_dir"
    target.mkdir()
    link_path = tmp_path / "link"

    def fake_symlink(*args, **kwargs):
        raise OSError(errno.EACCES, "denied")

    monkeypatch.setattr(linking.os, "symlink", fake_symlink)
    monkeypatch.setattr(linking, "is_windows", lambda: False)
    with pytest.raises(linking.LinkingError, match="Échec"):
        linking._create_symlink(link_path, target, target_is_dir=True)


def test_replace_with_hardlink_symlink_already_correct(tmp_path):
    source = tmp_path / "source.lsx"
    source.write_text("data")
    original = tmp_path / "original.lsx"
    original.symlink_to(source)
    linking._replace_with_hardlink(original, source)  # no-op, ne lève pas
    assert original.is_symlink()


def test_replace_with_hardlink_symlink_wrong_target_replaced(tmp_path):
    source = tmp_path / "source.lsx"
    source.write_text("data")
    other = tmp_path / "other.lsx"
    other.write_text("other")
    original = tmp_path / "original.lsx"
    original.symlink_to(other)
    linking._replace_with_hardlink(original, source)
    assert original.stat().st_ino == source.stat().st_ino


def test_replace_with_hardlink_already_same_inode(tmp_path):
    source = tmp_path / "source.lsx"
    source.write_text("data")
    original = tmp_path / "original.lsx"
    original.hardlink_to(source)
    linking._replace_with_hardlink(original, source)  # no-op
    assert original.stat().st_ino == source.stat().st_ino


def test_replace_with_hardlink_backs_up_existing_file(tmp_path):
    source = tmp_path / "source.lsx"
    source.write_text("new-data")
    original = tmp_path / "original.lsx"
    original.write_text("old-data")
    linking._replace_with_hardlink(original, source)
    backup = tmp_path / "original.lsx.bak"
    assert backup.read_text() == "old-data"
    assert original.stat().st_ino == source.stat().st_ino


def test_replace_with_hardlink_oserror_raises(tmp_path, monkeypatch):
    source = tmp_path / "source.lsx"
    source.write_text("data")
    original = tmp_path / "original.lsx"
    original.write_text("old")

    def fake_link_or_symlink(_source, _target):
        raise OSError("boom")

    monkeypatch.setattr(linking, "link_or_symlink", fake_link_or_symlink)
    with pytest.raises(linking.LinkingError):
        linking._replace_with_hardlink(original, source)


def test_setup_links_windows_requires_admin(cfg, monkeypatch):
    monkeypatch.setattr(linking, "is_windows", lambda: True)
    monkeypatch.setattr(linking, "can_create_links_without_admin", lambda: False)
    with pytest.raises(linking.LinkingError, match="administrateur"):
        linking.setup_links(cfg)


def test_setup_links_missing_appdata_mods_dir(cfg):
    with pytest.raises(linking.LinkingError, match="Mods"):
        linking.setup_links(cfg)


def test_setup_links_missing_install_dir(cfg, monkeypatch):
    cfg.appdata_mods_dir.mkdir(parents=True)
    cfg.appdata_modsettings_path.parent.mkdir(parents=True)
    cfg.appdata_modsettings_path.write_text("<settings/>")
    # Supprime le dossier d'installation créé par la fixture.
    import shutil

    shutil.rmtree(cfg.install_path)
    with pytest.raises(linking.LinkingError, match="installation"):
        linking.setup_links(cfg)


def test_setup_links_happy_path(cfg):
    cfg.appdata_mods_dir.mkdir(parents=True)
    cfg.appdata_modsettings_path.parent.mkdir(parents=True)
    cfg.appdata_modsettings_path.write_text("<settings/>")

    report = linking.setup_links(cfg)

    assert cfg.managed_mods_link.is_symlink()
    assert cfg.managed_modsettings_path.read_text() == "<settings/>"
    assert cfg.appdata_modsettings_path.stat().st_ino == cfg.managed_modsettings_path.stat().st_ino
    assert cfg.managed_install_link.is_symlink()
    assert len(report.steps) == 4


def test_setup_links_managed_modsettings_already_present(cfg):
    cfg.appdata_mods_dir.mkdir(parents=True)
    cfg.appdata_modsettings_path.parent.mkdir(parents=True)
    cfg.appdata_modsettings_path.write_text("<settings/>")
    cfg.managed_dir.mkdir(parents=True)
    cfg.managed_modsettings_path.write_text("<already-here/>")

    report = linking.setup_links(cfg)
    assert any("déjà présente" in step for step in report.steps)


def test_setup_links_missing_appdata_modsettings_raises(cfg):
    cfg.appdata_mods_dir.mkdir(parents=True)
    with pytest.raises(linking.LinkingError, match="introuvable"):
        linking.setup_links(cfg)
