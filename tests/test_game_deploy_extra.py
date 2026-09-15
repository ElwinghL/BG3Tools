"""Tests complémentaires pour bg3_mod_tui/game_deploy.py (voir
tests/test_game_deploy.py pour deploy_script_extender, déjà partiellement
couvert) : déploiement de Native Mod Loader, fichiers "loose", et
synchronisation des hardlinks entre profils. Tout se fait sur de vrais
fichiers/hardlinks sous tmp_path."""

from __future__ import annotations

import json

from bg3_mod_tui import game_deploy as gd


def _log_list():
    logs = []
    return logs, logs.append


# ---------------------------------------------------------------------------
# deploy_native_mod_loader
# ---------------------------------------------------------------------------


def test_deploy_native_mod_loader_source_missing_or_empty(tmp_path):
    logs, log = _log_list()
    gd.deploy_native_mod_loader(tmp_path / "Tools", tmp_path / "bin", log=log)
    assert any("rien à déployer" in m for m in logs)


def test_deploy_native_mod_loader_missing_game_bin_dir(tmp_path):
    source_bin = tmp_path / "Tools" / gd.NATIVE_MOD_LOADER_DIR_NAME / "bin"
    source_bin.mkdir(parents=True)
    (source_bin / gd.NML_HOOKED_DLL_NAME).write_bytes(b"loader")

    logs, log = _log_list()
    gd.deploy_native_mod_loader(tmp_path / "Tools", tmp_path / "missing_bin", log=log)
    assert any("bin/ du jeu introuvable" in m for m in logs)


def test_deploy_native_mod_loader_full_deploy_with_backup(tmp_path):
    source_bin = tmp_path / "Tools" / gd.NATIVE_MOD_LOADER_DIR_NAME / "bin"
    source_bin.mkdir(parents=True)
    (source_bin / gd.NML_HOOKED_DLL_NAME).write_bytes(b"loader")
    (source_bin / "extra.txt").write_text("extra", encoding="utf-8")

    game_bin = tmp_path / "bin"
    game_bin.mkdir()
    (game_bin / gd.NML_HOOKED_DLL_NAME).write_bytes(b"original-video-dll")

    logs, log = _log_list()
    gd.deploy_native_mod_loader(tmp_path / "Tools", game_bin, log=log)

    backup = game_bin / gd.NML_BACKUP_DLL_NAME
    assert backup.read_bytes() == b"original-video-dll"
    assert (game_bin / gd.NML_HOOKED_DLL_NAME).stat().st_ino == (
        source_bin / gd.NML_HOOKED_DLL_NAME
    ).stat().st_ino
    assert (game_bin / "extra.txt").read_text(encoding="utf-8") == "extra"
    assert any("terminé" in m for m in logs)


def test_deploy_native_mod_loader_missing_hooked_dll_logs(tmp_path):
    source_bin = tmp_path / "Tools" / gd.NATIVE_MOD_LOADER_DIR_NAME / "bin"
    source_bin.mkdir(parents=True)
    (source_bin / "other.dll").write_bytes(b"x")
    game_bin = tmp_path / "bin"
    game_bin.mkdir()

    logs, log = _log_list()
    gd.deploy_native_mod_loader(tmp_path / "Tools", game_bin, log=log)
    assert any("absent de" in m for m in logs)


def test_deploy_native_mod_loader_idempotent_rerun(tmp_path):
    source_bin = tmp_path / "Tools" / gd.NATIVE_MOD_LOADER_DIR_NAME / "bin"
    source_bin.mkdir(parents=True)
    (source_bin / gd.NML_HOOKED_DLL_NAME).write_bytes(b"loader")
    game_bin = tmp_path / "bin"
    game_bin.mkdir()

    gd.deploy_native_mod_loader(tmp_path / "Tools", game_bin, log=lambda m: None)
    logs, log = _log_list()
    gd.deploy_native_mod_loader(tmp_path / "Tools", game_bin, log=log)
    assert any("déjà un hardlink" in m for m in logs)
    # Le backup n'est jamais recréé une deuxième fois avec un contenu différent.
    assert not (game_bin / gd.NML_BACKUP_DLL_NAME).exists()


def test_deploy_native_mod_loader_backup_already_exists_just_unlinks(tmp_path):
    source_bin = tmp_path / "Tools" / gd.NATIVE_MOD_LOADER_DIR_NAME / "bin"
    source_bin.mkdir(parents=True)
    (source_bin / gd.NML_HOOKED_DLL_NAME).write_bytes(b"loader-v2")
    game_bin = tmp_path / "bin"
    game_bin.mkdir()
    (game_bin / gd.NML_HOOKED_DLL_NAME).write_bytes(b"some-other-file")
    (game_bin / gd.NML_BACKUP_DLL_NAME).write_bytes(b"already-backed-up")

    gd.deploy_native_mod_loader(tmp_path / "Tools", game_bin, log=lambda m: None)

    # Le backup existant n'a pas été écrasé.
    assert (game_bin / gd.NML_BACKUP_DLL_NAME).read_bytes() == b"already-backed-up"
    assert (game_bin / gd.NML_HOOKED_DLL_NAME).stat().st_ino == (
        source_bin / gd.NML_HOOKED_DLL_NAME
    ).stat().st_ino


def test_deploy_native_mod_loader_broken_symlink_target(tmp_path, monkeypatch):
    source_bin = tmp_path / "Tools" / gd.NATIVE_MOD_LOADER_DIR_NAME / "bin"
    source_bin.mkdir(parents=True)
    dll = source_bin / gd.NML_HOOKED_DLL_NAME
    dll.write_bytes(b"loader")
    game_bin = tmp_path / "bin"
    game_bin.mkdir()

    # Symlink existant pointant déjà vers la bonne source.
    target_dll = game_bin / gd.NML_HOOKED_DLL_NAME
    target_dll.symlink_to(dll)

    logs, log = _log_list()
    gd.deploy_native_mod_loader(tmp_path / "Tools", game_bin, log=log)
    assert any("déjà un lien vers" in m for m in logs)


# ---------------------------------------------------------------------------
# deploy_script_extender : branches supplémentaires
# ---------------------------------------------------------------------------


def test_deploy_script_extender_source_dir_missing(tmp_path):
    logs, log = _log_list()
    gd.deploy_script_extender(tmp_path / "Tools", tmp_path / "bin", log=log)
    assert any("dossier introuvable" in m for m in logs)


def test_deploy_script_extender_missing_game_bin_dir(tmp_path):
    source_dir = tmp_path / "Tools" / gd.SCRIPT_EXTENDER_DIR_NAME
    source_dir.mkdir(parents=True)
    (source_dir / "DWrite.dll").write_bytes(b"dll")

    logs, log = _log_list()
    gd.deploy_script_extender(tmp_path / "Tools", tmp_path / "missing_bin", log=log)
    assert any("bin/ du jeu introuvable" in m for m in logs)


def test_deploy_script_extender_migrates_existing_settings(tmp_path):
    source_dir = tmp_path / "Tools" / gd.SCRIPT_EXTENDER_DIR_NAME
    source_dir.mkdir(parents=True)
    (source_dir / "DWrite.dll").write_bytes(b"dll")
    game_bin = tmp_path / "bin"
    game_bin.mkdir()
    (game_bin / gd.SCRIPT_EXTENDER_SETTINGS_NAME).write_text('{"custom": true}', encoding="utf-8")

    logs, log = _log_list()
    gd.deploy_script_extender(tmp_path / "Tools", game_bin, log=log)

    managed_settings = source_dir / gd.SCRIPT_EXTENDER_SETTINGS_NAME
    assert json.loads(managed_settings.read_text(encoding="utf-8")) == {"custom": True}
    assert any("migrée" in m for m in logs)


def test_deploy_script_extender_keeps_existing_managed_settings(tmp_path):
    source_dir = tmp_path / "Tools" / gd.SCRIPT_EXTENDER_DIR_NAME
    source_dir.mkdir(parents=True)
    (source_dir / "DWrite.dll").write_bytes(b"dll")
    (source_dir / gd.SCRIPT_EXTENDER_SETTINGS_NAME).write_text(
        '{"already": "managed"}', encoding="utf-8"
    )
    game_bin = tmp_path / "bin"
    game_bin.mkdir()

    logs, log = _log_list()
    gd.deploy_script_extender(tmp_path / "Tools", game_bin, log=log)
    assert any("conservée" in m for m in logs)
    data = json.loads((game_bin / gd.SCRIPT_EXTENDER_SETTINGS_NAME).read_text(encoding="utf-8"))
    assert data == {"already": "managed"}


def test_deploy_script_extender_linux_reminder(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "is_windows", lambda: False)
    source_dir = tmp_path / "Tools" / gd.SCRIPT_EXTENDER_DIR_NAME
    source_dir.mkdir(parents=True)
    (source_dir / "DWrite.dll").write_bytes(b"dll")
    game_bin = tmp_path / "bin"
    game_bin.mkdir()

    logs, log = _log_list()
    gd.deploy_script_extender(tmp_path / "Tools", game_bin, log=log)
    assert any("Steam" in m for m in logs)


def test_deploy_script_extender_windows_no_reminder(tmp_path, monkeypatch):
    monkeypatch.setattr(gd, "is_windows", lambda: True)
    source_dir = tmp_path / "Tools" / gd.SCRIPT_EXTENDER_DIR_NAME
    source_dir.mkdir(parents=True)
    (source_dir / "DWrite.dll").write_bytes(b"dll")
    game_bin = tmp_path / "bin"
    game_bin.mkdir()

    logs, log = _log_list()
    gd.deploy_script_extender(tmp_path / "Tools", game_bin, log=log)
    assert not any("Steam" in m for m in logs)


def test_deploy_script_extender_idempotent_rerun(tmp_path):
    source_dir = tmp_path / "Tools" / gd.SCRIPT_EXTENDER_DIR_NAME
    source_dir.mkdir(parents=True)
    (source_dir / "DWrite.dll").write_bytes(b"dll")
    game_bin = tmp_path / "bin"
    game_bin.mkdir()

    gd.deploy_script_extender(tmp_path / "Tools", game_bin, log=lambda m: None)
    logs, log = _log_list()
    gd.deploy_script_extender(tmp_path / "Tools", game_bin, log=log)
    assert any("déjà un hardlink" in m for m in logs)


# ---------------------------------------------------------------------------
# deploy_loose_files
# ---------------------------------------------------------------------------


def test_deploy_loose_files_missing_managed_dir(tmp_path):
    assert gd.deploy_loose_files(tmp_path / "missing", tmp_path / "Data", log=lambda m: None) == 0


def test_deploy_loose_files_missing_game_data_dir(tmp_path):
    managed = tmp_path / "DataMods"
    managed.mkdir()
    logs, log = _log_list()
    count = gd.deploy_loose_files(managed, tmp_path / "missing_data", log=log)
    assert count == 0
    assert any("Data/ du jeu introuvable" in m for m in logs)


def test_deploy_loose_files_links_all_files(tmp_path):
    managed = tmp_path / "DataMods"
    (managed / "Public" / "Sub").mkdir(parents=True)
    (managed / "Public" / "Sub" / "file1.txt").write_text("1", encoding="utf-8")
    (managed / "Generated" / "file2.txt").parent.mkdir(parents=True)
    (managed / "Generated" / "file2.txt").write_text("2", encoding="utf-8")

    game_data = tmp_path / "Data"
    game_data.mkdir()

    count = gd.deploy_loose_files(managed, game_data, log=lambda m: None)
    assert count == 2
    assert (game_data / "Public" / "Sub" / "file1.txt").read_text(encoding="utf-8") == "1"
    assert (game_data / "Generated" / "file2.txt").read_text(encoding="utf-8") == "2"


# ---------------------------------------------------------------------------
# remove_stale_hardlinks
# ---------------------------------------------------------------------------


def test_remove_stale_hardlinks_missing_dir_returns_zero(tmp_path):
    assert gd.remove_stale_hardlinks(tmp_path / "missing", {"a.txt"}, log=lambda m: None) == 0


def test_remove_stale_hardlinks_removes_only_listed(tmp_path):
    target_dir = tmp_path / "Data"
    target_dir.mkdir()
    (target_dir / "a.txt").write_bytes(b"a")
    (target_dir / "b.txt").write_bytes(b"b")

    logs, log = _log_list()
    removed = gd.remove_stale_hardlinks(target_dir, {"a.txt", "missing.txt"}, log=log)
    assert removed == 1
    assert not (target_dir / "a.txt").exists()
    assert (target_dir / "b.txt").exists()
    assert any("hardlink retiré" in m for m in logs)


# ---------------------------------------------------------------------------
# sync_hardlinked_files
# ---------------------------------------------------------------------------


def test_sync_hardlinked_files_full_cycle(tmp_path):
    managed_dir = tmp_path / "DataMods"
    managed_dir.mkdir()
    (managed_dir / "keep.txt").write_text("keep", encoding="utf-8")
    (managed_dir / "new.txt").write_text("new", encoding="utf-8")

    target_dir = tmp_path / "Data"
    target_dir.mkdir()
    (target_dir / "stale.txt").write_bytes(b"stale")

    logs, log = _log_list()
    linked = gd.sync_hardlinked_files(
        managed_dir,
        target_dir,
        wanted={"keep.txt", "new.txt"},
        previously_linked={"keep.txt", "stale.txt"},
        log=log,
    )
    assert linked == {"keep.txt", "new.txt"}
    assert not (target_dir / "stale.txt").exists()
    assert (target_dir / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert (target_dir / "new.txt").read_text(encoding="utf-8") == "new"


def test_sync_hardlinked_files_missing_managed_dir_returns_empty(tmp_path):
    linked = gd.sync_hardlinked_files(
        tmp_path / "missing_managed",
        tmp_path / "Data",
        wanted={"a.txt"},
        previously_linked=set(),
        log=lambda m: None,
    )
    assert linked == set()


def test_sync_hardlinked_files_missing_source_file_logged(tmp_path):
    managed_dir = tmp_path / "DataMods"
    managed_dir.mkdir()
    target_dir = tmp_path / "Data"

    logs, log = _log_list()
    linked = gd.sync_hardlinked_files(
        managed_dir, target_dir, wanted={"gone.txt"}, previously_linked=set(), log=log
    )
    assert linked == set()
    assert any("source absente" in m for m in logs)
