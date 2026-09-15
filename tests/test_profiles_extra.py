"""Tests complémentaires pour bg3_mod_tui/profiles.py (voir
tests/test_profiles.py pour slugify_profile_name/manifest_file_names, déjà
couverts) : sauvegarde/restauration de profil, données annexes (blacklist
Nexus, hardlinks), profil Default, découverte des profils du jeu. Tout se
fait sur de vrais fichiers sous tmp_path (les hardlinks fonctionnent
normalement dans un même système de fichiers) ; aucun accès réseau."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bg3_mod_tui import profiles as pf
from bg3_mod_tui.inventory import ArchiveEntry


# ---------------------------------------------------------------------------
# ensure_default_profile
# ---------------------------------------------------------------------------


def test_ensure_default_profile_noop_if_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "_DEFAULT_PROFILE_SOURCE", tmp_path / "missing_source")
    profiles_dir = tmp_path / "profiles"
    pf.ensure_default_profile(profiles_dir)
    assert not profiles_dir.exists()


def test_ensure_default_profile_installs_from_source(tmp_path, monkeypatch):
    source = tmp_path / "default_profile"
    source.mkdir()
    (source / pf.MODSETTINGS_FILENAME).write_text("<settings/>", encoding="utf-8")
    (source / pf.MANIFEST_FILENAME).write_text('{"name": "Default"}', encoding="utf-8")
    monkeypatch.setattr(pf, "_DEFAULT_PROFILE_SOURCE", source)

    profiles_dir = tmp_path / "profiles"
    pf.ensure_default_profile(profiles_dir)

    dest = profiles_dir / pf.slugify_profile_name(pf.DEFAULT_PROFILE_NAME)
    assert (dest / pf.MODSETTINGS_FILENAME).read_text(encoding="utf-8") == "<settings/>"
    assert (dest / pf.MANIFEST_FILENAME).is_file()


def test_ensure_default_profile_noop_if_already_installed(tmp_path, monkeypatch):
    source = tmp_path / "default_profile"
    source.mkdir()
    (source / pf.MANIFEST_FILENAME).write_text('{"name": "Default"}', encoding="utf-8")
    monkeypatch.setattr(pf, "_DEFAULT_PROFILE_SOURCE", source)

    profiles_dir = tmp_path / "profiles"
    dest = profiles_dir / pf.slugify_profile_name(pf.DEFAULT_PROFILE_NAME)
    dest.mkdir(parents=True)
    (dest / pf.MANIFEST_FILENAME).write_text(
        '{"name": "Default", "already": true}', encoding="utf-8"
    )

    pf.ensure_default_profile(profiles_dir)
    data = json.loads((dest / pf.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert data["already"] is True  # pas écrasé


# ---------------------------------------------------------------------------
# profile_data_dir / blacklist
# ---------------------------------------------------------------------------


def test_profile_data_dir_with_and_without_profile(tmp_path):
    profiles_dir = tmp_path / "profiles"
    assert pf.profile_data_dir(profiles_dir, "My Profile") == profiles_dir / "My_Profile"
    assert pf.profile_data_dir(profiles_dir, "") == profiles_dir / pf._NO_PROFILE_SLUG


def test_load_blacklisted_files_missing_returns_empty(tmp_path):
    assert pf.load_blacklisted_files(tmp_path, "Profile") == {}


def test_save_and_load_blacklisted_files_roundtrip(tmp_path):
    blacklist = {5447: {1: "file1.zip", 2: "file2.zip"}, 999: {}}
    pf.save_blacklisted_files(tmp_path, "Profile", blacklist)
    loaded = pf.load_blacklisted_files(tmp_path, "Profile")
    # Les entrées vides ne sont pas sérialisées.
    assert loaded == {5447: {1: "file1.zip", 2: "file2.zip"}}


def test_load_blacklisted_files_invalid_json_returns_empty(tmp_path):
    dest_dir = pf.profile_data_dir(tmp_path, "Profile")
    dest_dir.mkdir(parents=True)
    (dest_dir / pf.FILE_CHOICES_FILENAME).write_text("not json", encoding="utf-8")
    assert pf.load_blacklisted_files(tmp_path, "Profile") == {}


# ---------------------------------------------------------------------------
# sync_game_profile
# ---------------------------------------------------------------------------


def test_sync_game_profile_unrecognized_structure_returns_none(tmp_path):
    modsettings = tmp_path / "SomeDir" / "modsettings.lsx"
    modsettings.parent.mkdir(parents=True)
    modsettings.write_text("<settings/>", encoding="utf-8")
    result = pf.sync_game_profile(modsettings, "Name", modsettings)
    assert result is None


def test_sync_game_profile_source_missing_returns_none(tmp_path):
    modsettings = tmp_path / "PlayerProfiles" / "Public" / "modsettings.lsx"
    modsettings.parent.mkdir(parents=True)
    result = pf.sync_game_profile(modsettings, "Name", tmp_path / "missing.lsx")
    assert result is None


def test_sync_game_profile_creates_and_updates(tmp_path):
    modsettings = tmp_path / "PlayerProfiles" / "Public" / "modsettings.lsx"
    modsettings.parent.mkdir(parents=True)
    source = tmp_path / "source_modsettings.lsx"
    source.write_text("<settings v='1'/>", encoding="utf-8")

    result = pf.sync_game_profile(modsettings, "My Profile", source)
    assert result == tmp_path / "PlayerProfiles" / "My_Profile"
    target = result / pf.MODSETTINGS_FILENAME
    assert target.read_text(encoding="utf-8") == "<settings v='1'/>"

    # Deuxième appel avec un contenu source différent : le fichier cible
    # doit être mis à jour.
    source.write_text("<settings v='2'/>", encoding="utf-8")
    pf.sync_game_profile(modsettings, "My Profile", source)
    assert target.read_text(encoding="utf-8") == "<settings v='2'/>"


def test_sync_game_profile_noop_if_identical(tmp_path):
    modsettings = tmp_path / "PlayerProfiles" / "Public" / "modsettings.lsx"
    modsettings.parent.mkdir(parents=True)
    source = tmp_path / "source_modsettings.lsx"
    source.write_text("<settings/>", encoding="utf-8")

    result = pf.sync_game_profile(modsettings, "My Profile", source)
    target = result / pf.MODSETTINGS_FILENAME
    mtime_before = target.stat().st_mtime_ns

    pf.sync_game_profile(modsettings, "My Profile", source)
    assert target.stat().st_mtime_ns == mtime_before


# ---------------------------------------------------------------------------
# save_profile
# ---------------------------------------------------------------------------


@pytest.fixture
def deploy_layout(tmp_path):
    modsettings = tmp_path / "AppData" / "PlayerProfiles" / "Public" / "modsettings.lsx"
    modsettings.parent.mkdir(parents=True)
    modsettings.write_text("<settings/>", encoding="utf-8")

    mods_dir = tmp_path / "Mods"
    mods_dir.mkdir()
    (mods_dir / "ModA.pak").write_bytes(b"")
    (mods_dir / "ModB.pak").write_bytes(b"")

    native_mods_dir = tmp_path / "NativeMods"
    native_mods_dir.mkdir()
    (native_mods_dir / "native.dll").write_bytes(b"")

    loose_mods_dir = tmp_path / "DataMods"
    (loose_mods_dir / "sub").mkdir(parents=True)
    (loose_mods_dir / "sub" / "file.txt").write_text("loose", encoding="utf-8")

    return {
        "modsettings": modsettings,
        "mods_dir": mods_dir,
        "native_mods_dir": native_mods_dir,
        "loose_mods_dir": loose_mods_dir,
    }


def test_save_profile_missing_modsettings_raises(tmp_path):
    with pytest.raises(pf.ProfileError, match="introuvable"):
        pf.save_profile(
            "Test",
            profiles_dir=tmp_path / "profiles",
            modsettings_path=tmp_path / "missing.lsx",
            mods_dir=tmp_path / "Mods",
            loose_mods_dir=tmp_path / "DataMods",
        )


def test_save_profile_builds_manifest(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    archives = [
        ArchiveEntry(
            file="ModA-5447-1-0.zip",
            status="installee",
            size_bytes=100,
            modified="2024-01-01",
            nexus_mod_id=5447,
            nexus_url="http://x",
            version="1.0",
            mod_name_guess="ModA",
        )
    ]

    dest = pf.save_profile(
        "My Profile",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
        native_mods_dir=deploy_layout["native_mods_dir"],
        archives=archives,
    )

    assert dest == profiles_dir / "My_Profile"
    manifest = json.loads((dest / pf.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["name"] == "My Profile"
    pak_files = {e["file"] for e in manifest["paks"]}
    assert pak_files == {"ModA.pak", "ModB.pak"}
    mod_a_entry = next(e for e in manifest["paks"] if e["file"] == "ModA.pak")
    assert mod_a_entry["origin"]["nexus_mod_id"] == 5447
    assert manifest["native_mods"][0]["file"] == "native.dll"
    assert manifest["loose_files"] == ["sub/file.txt"]
    assert (dest / pf.MODSETTINGS_FILENAME).is_file()


def test_save_profile_no_optional_dirs(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    dest = pf.save_profile(
        "Minimal",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=tmp_path / "missing_mods",
        loose_mods_dir=tmp_path / "missing_loose",
    )
    manifest = json.loads((dest / pf.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["paks"] == []
    assert manifest["native_mods"] == []
    assert manifest["loose_files"] == []


# ---------------------------------------------------------------------------
# find_profile_dir
# ---------------------------------------------------------------------------


def test_find_profile_dir_direct_slug(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    pf.save_profile(
        "MyProfile",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
    )
    found = pf.find_profile_dir(profiles_dir, "MyProfile")
    assert found == profiles_dir / "MyProfile"


def test_find_profile_dir_falls_back_to_manifest_name_scan(tmp_path):
    profiles_dir = tmp_path / "profiles"
    weird_dir = profiles_dir / "some_slug"
    weird_dir.mkdir(parents=True)
    (weird_dir / pf.MANIFEST_FILENAME).write_text(
        json.dumps({"name": "Weird Name!!"}), encoding="utf-8"
    )
    found = pf.find_profile_dir(profiles_dir, "Weird Name!!")
    assert found == weird_dir


def test_find_profile_dir_skips_invalid_manifests_and_raises(tmp_path):
    profiles_dir = tmp_path / "profiles"
    bad_dir = profiles_dir / "bad"
    bad_dir.mkdir(parents=True)
    (bad_dir / pf.MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
    with pytest.raises(pf.ProfileError, match="introuvable"):
        pf.find_profile_dir(profiles_dir, "Unknown")


def test_find_profile_dir_missing_profiles_dir_raises(tmp_path):
    with pytest.raises(pf.ProfileError):
        pf.find_profile_dir(tmp_path / "missing", "Anything")


# ---------------------------------------------------------------------------
# load_profile_hardlinks / save_profile_hardlinks
# ---------------------------------------------------------------------------


def test_load_profile_hardlinks_missing_returns_empty(tmp_path):
    assert pf.load_profile_hardlinks(tmp_path) == {"loose_files": [], "native_mods": []}


def test_load_profile_hardlinks_invalid_json_returns_empty(tmp_path):
    (tmp_path / pf.HARDLINKS_FILENAME).write_text("not json", encoding="utf-8")
    assert pf.load_profile_hardlinks(tmp_path) == {"loose_files": [], "native_mods": []}


def test_save_and_load_profile_hardlinks_roundtrip(tmp_path):
    pf.save_profile_hardlinks(tmp_path, loose_files={"b.txt", "a.txt"}, native_mods={"x.dll"})
    loaded = pf.load_profile_hardlinks(tmp_path)
    assert loaded == {"loose_files": ["a.txt", "b.txt"], "native_mods": ["x.dll"]}


# ---------------------------------------------------------------------------
# restore_profile (bout en bout, vrais hardlinks sous tmp_path)
# ---------------------------------------------------------------------------


def test_restore_profile_missing_modsettings_raises(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    profile_dir = profiles_dir / "Broken"
    profile_dir.mkdir(parents=True)
    (profile_dir / pf.MANIFEST_FILENAME).write_text(
        json.dumps({"name": "Broken"}), encoding="utf-8"
    )

    with pytest.raises(pf.ProfileError, match="modsettings.lsx manquant"):
        pf.restore_profile(
            "Broken",
            profiles_dir=profiles_dir,
            modsettings_path=deploy_layout["modsettings"],
            mods_dir=deploy_layout["mods_dir"],
            loose_mods_dir=deploy_layout["loose_mods_dir"],
            game_data_dir=tmp_path / "Data",
        )


def test_restore_profile_full_flow(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    pf.save_profile(
        "Full",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
        native_mods_dir=deploy_layout["native_mods_dir"],
    )

    # Change modsettings.lsx pour vérifier qu'il est bien restauré.
    deploy_layout["modsettings"].write_text("<settings changed='1'/>", encoding="utf-8")

    game_data_dir = tmp_path / "Data"
    logs = []
    report = pf.restore_profile(
        "Full",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
        game_data_dir=game_data_dir,
        native_mods_dir=deploy_layout["native_mods_dir"],
        log=logs.append,
    )

    assert deploy_layout["modsettings"].read_text(encoding="utf-8") == "<settings/>"
    assert report.loose_files_linked == 1
    assert (game_data_dir / "sub" / "file.txt").is_file()
    assert report.paks_missing == []
    assert report.paks_extra == []
    assert report.native_mods_missing == []
    assert any("restauré" in m for m in logs)

    hardlinks = pf.load_profile_hardlinks(pf.find_profile_dir(profiles_dir, "Full"))
    assert hardlinks["loose_files"] == ["sub/file.txt"]
    assert hardlinks["native_mods"] == ["native.dll"]


def test_restore_profile_switch_removes_stale_native_mod(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    game_data_dir = tmp_path / "Data"

    # Profil A : avec le mod natif.
    pf.save_profile(
        "A",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
        native_mods_dir=deploy_layout["native_mods_dir"],
    )
    pf.restore_profile(
        "A",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
        game_data_dir=game_data_dir,
        native_mods_dir=deploy_layout["native_mods_dir"],
    )

    # Profil B : sans le fichier natif dans le manifeste (mods_dir/native
    # vides au moment de la sauvegarde).
    empty_mods_dir = tmp_path / "EmptyMods"
    empty_mods_dir.mkdir()
    empty_native_dir = tmp_path / "EmptyNative"
    empty_native_dir.mkdir()
    pf.save_profile(
        "B",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=empty_mods_dir,
        loose_mods_dir=tmp_path / "EmptyLoose",
        native_mods_dir=empty_native_dir,
    )

    assert (deploy_layout["native_mods_dir"] / "native.dll").is_file()
    report = pf.restore_profile(
        "B",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=empty_mods_dir,
        loose_mods_dir=tmp_path / "EmptyLoose",
        game_data_dir=game_data_dir,
        native_mods_dir=deploy_layout["native_mods_dir"],
        previous_profile="A",
    )

    # Le hardlink natif du profil A, absent du manifeste B, a été retiré.
    assert not (deploy_layout["native_mods_dir"] / "native.dll").exists()
    assert report.native_mods_missing == []


def test_restore_profile_reports_missing_and_extra_paks(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    pf.save_profile(
        "Full",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
    )

    # Simule un .pak supprimé depuis la sauvegarde, et un nouveau présent
    # mais pas dans le manifeste.
    (deploy_layout["mods_dir"] / "ModA.pak").unlink()
    (deploy_layout["mods_dir"] / "ModC.pak").write_bytes(b"")

    report = pf.restore_profile(
        "Full",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
        game_data_dir=tmp_path / "Data",
    )
    assert report.paks_missing == ["ModA.pak"]
    assert report.paks_extra == ["ModC.pak"]


def test_restore_profile_previous_profile_not_found_is_ignored(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    pf.save_profile(
        "Full",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
    )
    # previous_profile inconnu : ne doit pas lever.
    pf.restore_profile(
        "Full",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
        game_data_dir=tmp_path / "Data",
        previous_profile="GhostProfile",
    )


# ---------------------------------------------------------------------------
# list_profiles
# ---------------------------------------------------------------------------


def test_list_profiles_missing_dir_returns_empty(tmp_path):
    assert pf.list_profiles(tmp_path / "missing") == []


def test_list_profiles_sorted_by_name(tmp_path, deploy_layout):
    profiles_dir = tmp_path / "profiles"
    pf.save_profile(
        "Zebra",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
    )
    pf.save_profile(
        "Alpha",
        profiles_dir=profiles_dir,
        modsettings_path=deploy_layout["modsettings"],
        mods_dir=deploy_layout["mods_dir"],
        loose_mods_dir=deploy_layout["loose_mods_dir"],
    )
    assert pf.list_profiles(profiles_dir) == ["Alpha", "Zebra"]


def test_list_profiles_invalid_manifest_falls_back_to_dirname(tmp_path):
    profiles_dir = tmp_path / "profiles"
    bad_dir = profiles_dir / "bad_slug"
    bad_dir.mkdir(parents=True)
    (bad_dir / pf.MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
    assert pf.list_profiles(profiles_dir) == ["bad_slug"]


def test_list_profiles_ignores_dirs_without_manifest(tmp_path):
    profiles_dir = tmp_path / "profiles"
    (profiles_dir / "not_a_profile").mkdir(parents=True)
    assert pf.list_profiles(profiles_dir) == []
