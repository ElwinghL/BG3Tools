"""Tests complémentaires pour bg3_mod_tui/inventory.py (voir
tests/test_inventory.py pour known_mod_ids/known_modio_ids déjà couverts) :
scan_all_archives, build_inventory, find_orphaned_archives, save_inventory
et l'association heuristique pak<->archive. Tout sur de vrais fichiers
sous tmp_path."""

from __future__ import annotations

import json

from bg3_mod_tui import inventory as inv


# ---------------------------------------------------------------------------
# scan_all_archives / _scan_archives
# ---------------------------------------------------------------------------


def test_scan_all_archives_empty_dirs(tmp_path):
    progress = []
    archives = inv.scan_all_archives(
        archives_dir=tmp_path / "avail",
        archives_installed_dir=tmp_path / "installed",
        archives_pending_dir=tmp_path / "pending",
        on_progress=progress.append,
    )
    assert archives == []
    assert any("disponibles" in m for m in progress)


def test_scan_all_archives_finds_files_with_metadata(tmp_path):
    avail = tmp_path / "avail"
    avail.mkdir()
    (avail / "CoolMod-5447-1-2-1690000000.zip").write_bytes(b"data")
    (avail / "not_an_archive.txt").write_bytes(b"x")
    installed = tmp_path / "installed"
    installed.mkdir()
    (installed / "OtherMod.rar").write_bytes(b"data")

    archives = inv.scan_all_archives(
        archives_dir=avail,
        archives_installed_dir=installed,
        archives_pending_dir=tmp_path / "pending",
    )
    files = {a.file for a in archives}
    assert files == {"CoolMod-5447-1-2-1690000000.zip", "OtherMod.rar"}
    cool = next(a for a in archives if a.file == "CoolMod-5447-1-2-1690000000.zip")
    assert cool.status == "disponible"
    assert cool.nexus_mod_id == 5447
    other = next(a for a in archives if a.file == "OtherMod.rar")
    assert other.status == "installee"
    assert other.nexus_mod_id is None


# ---------------------------------------------------------------------------
# _match_pak_to_archive / match_archive_origin
# ---------------------------------------------------------------------------


def test_match_pak_to_archive_no_match_empty_stem():
    assert inv._match_pak_to_archive("", []) is None


def test_match_pak_to_archive_picks_best_score():
    archives = [
        inv.ArchiveEntry(
            file="A.zip", status="disponible", size_bytes=1, modified="", mod_name_guess="Cool"
        ),
        inv.ArchiveEntry(
            file="B.zip",
            status="disponible",
            size_bytes=1,
            modified="",
            mod_name_guess="CoolModExtended",
        ),
    ]
    result = inv._match_pak_to_archive("CoolModExtendedPak", archives)
    assert result == "B.zip"


def test_match_pak_to_archive_no_candidate_matches():
    archives = [
        inv.ArchiveEntry(
            file="A.zip", status="disponible", size_bytes=1, modified="", mod_name_guess="Zzz"
        )
    ]
    assert inv._match_pak_to_archive("Completely Different", archives) is None


def test_match_pak_to_archive_skips_archive_with_empty_normalized_name():
    archives = [
        inv.ArchiveEntry(
            file="A.zip", status="disponible", size_bytes=1, modified="", mod_name_guess="---"
        )
    ]
    assert inv._match_pak_to_archive("SomePak", archives) is None


def test_match_archive_origin_none_when_no_match():
    assert inv.match_archive_origin("Unmatched", []) is None


def test_match_archive_origin_returns_fields():
    archives = [
        inv.ArchiveEntry(
            file="CoolMod-5447-1-0.zip",
            status="installee",
            size_bytes=1,
            modified="",
            nexus_mod_id=5447,
            nexus_url="http://x",
            version="1.0",
            mod_name_guess="CoolMod",
        )
    ]
    origin = inv.match_archive_origin("CoolMod", archives)
    assert origin == {
        "archive": "CoolMod-5447-1-0.zip",
        "nexus_mod_id": 5447,
        "nexus_url": "http://x",
        "version": "1.0",
        "mod_name_guess": "CoolMod",
    }


# ---------------------------------------------------------------------------
# build_inventory
# ---------------------------------------------------------------------------


def test_build_inventory_no_mods_dir(tmp_path):
    result = inv.build_inventory(
        mods_dir=tmp_path / "missing_mods",
        archives_dir=tmp_path / "avail",
        archives_installed_dir=tmp_path / "installed",
        archives_pending_dir=tmp_path / "pending",
    )
    assert result["paks"] == []
    assert result["counts"]["paks"] == 0


def test_build_inventory_matches_paks_to_archives(tmp_path):
    avail = tmp_path / "avail"
    avail.mkdir()
    (avail / "CoolMod-5447-1-0-1690000000.zip").write_bytes(b"data")

    mods_dir = tmp_path / "Mods"
    mods_dir.mkdir()
    (mods_dir / "CoolMod.pak").write_bytes(b"pak")
    (mods_dir / "Unmatched.pak").write_bytes(b"pak")

    progress = []
    result = inv.build_inventory(
        mods_dir=mods_dir,
        archives_dir=avail,
        archives_installed_dir=tmp_path / "installed",
        archives_pending_dir=tmp_path / "pending",
        on_progress=progress.append,
    )
    assert result["counts"]["paks"] == 2
    assert result["counts"]["archives"] == 1
    assert result["counts"]["archives_with_nexus_id"] == 1
    pak_names = {p["file"]: p["matched_archive"] for p in result["paks"]}
    assert pak_names["CoolMod.pak"] == "CoolMod-5447-1-0-1690000000.zip"
    assert pak_names["Unmatched.pak"] is None
    assert any("Association" in m for m in progress)


def test_build_inventory_progress_every_n_paks(tmp_path):
    mods_dir = tmp_path / "Mods"
    mods_dir.mkdir()
    for i in range(5):
        (mods_dir / f"Mod{i}.pak").write_bytes(b"pak")

    progress = []
    inv.build_inventory(
        mods_dir=mods_dir,
        archives_dir=tmp_path / "avail",
        archives_installed_dir=tmp_path / "installed",
        archives_pending_dir=tmp_path / "pending",
        on_progress=progress.append,
    )
    assert any("/5 .pak traités" in m for m in progress)


# ---------------------------------------------------------------------------
# find_orphaned_archives
# ---------------------------------------------------------------------------


def test_find_orphaned_archives_finds_unreferenced_installed():
    inventory = {
        "paks": [{"file": "A.pak", "matched_archive": "A.zip"}],
        "archives": [
            {"file": "A.zip", "status": "installee"},
            {"file": "B.zip", "status": "installee"},
            {"file": "C.zip", "status": "disponible"},
        ],
    }
    orphaned = inv.find_orphaned_archives(inventory)
    assert [a["file"] for a in orphaned] == ["B.zip"]


def test_find_orphaned_archives_excludes_native_manifest_entries():
    inventory = {
        "paks": [],
        "archives": [{"file": "Native.zip", "status": "installee"}],
    }
    orphaned = inv.find_orphaned_archives(inventory, native_manifest={"Native.zip": "native.dll"})
    assert orphaned == []


def test_find_orphaned_archives_no_native_manifest():
    inventory = {"paks": [], "archives": [{"file": "A.zip", "status": "installee"}]}
    orphaned = inv.find_orphaned_archives(inventory, native_manifest=None)
    assert [a["file"] for a in orphaned] == ["A.zip"]


# ---------------------------------------------------------------------------
# save_inventory
# ---------------------------------------------------------------------------


def test_save_inventory_writes_json(tmp_path):
    dest = tmp_path / "sub" / "inventory.json"
    inv.save_inventory({"a": 1}, dest)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data == {"a": 1}
