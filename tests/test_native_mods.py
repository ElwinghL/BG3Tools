"""Tests pour bg3_mod_tui.native_mods."""

from __future__ import annotations

import json
import zipfile

import pytest

from bg3_mod_tui import native_mods as nm
from bg3_mod_tui.archives import ArchiveError


def _make_zip(path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_load_manifest_missing_file(tmp_path):
    assert nm.load_manifest(tmp_path / "missing.json") == {}


def test_load_manifest_invalid_json(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("not json")
    with pytest.raises(nm.NativeModsManifestError):
        nm.load_manifest(manifest)


def test_load_manifest_wrong_shape(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"a": 1}))
    with pytest.raises(nm.NativeModsManifestError):
        nm.load_manifest(manifest)


def test_load_manifest_not_a_dict(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(["a", "b"]))
    with pytest.raises(nm.NativeModsManifestError):
        nm.load_manifest(manifest)


def test_load_manifest_valid(tmp_path):
    manifest = tmp_path / "manifest.json"
    data = {"mod.zip": "Installation BG3/bin/NativeMods"}
    manifest.write_text(json.dumps(data))
    assert nm.load_manifest(manifest) == data


def test_resolve_dest_dir_rejects_absolute(tmp_path):
    with pytest.raises(nm.NativeModsManifestError):
        nm._resolve_dest_dir(tmp_path, "/etc")


def test_resolve_dest_dir_rejects_dotdot(tmp_path):
    with pytest.raises(nm.NativeModsManifestError):
        nm._resolve_dest_dir(tmp_path, "../escape")


def test_resolve_dest_dir_normal(tmp_path):
    result = nm._resolve_dest_dir(tmp_path, "Installation BG3/bin/NativeMods")
    assert result == tmp_path / "Installation BG3" / "bin" / "NativeMods"


def test_hardlink_into_new_target(tmp_path):
    source = tmp_path / "src" / "file.dll"
    source.parent.mkdir()
    source.write_text("dll-bytes")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    logs: list[str] = []
    nm._hardlink_into(dest_dir, source, log=logs.append)
    target = dest_dir / "file.dll"
    assert target.stat().st_ino == source.stat().st_ino
    assert any("relié" in msg for msg in logs)


def test_hardlink_into_already_linked(tmp_path):
    source = tmp_path / "src" / "file.dll"
    source.parent.mkdir()
    source.write_text("dll-bytes")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    target = dest_dir / "file.dll"
    target.hardlink_to(source)
    logs: list[str] = []
    nm._hardlink_into(dest_dir, source, log=logs.append)
    assert any("déjà relié" in msg for msg in logs)


def test_hardlink_into_replaces_stale_target(tmp_path):
    source = tmp_path / "src" / "file.dll"
    source.parent.mkdir()
    source.write_text("new-bytes")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    target = dest_dir / "file.dll"
    target.write_text("old-bytes")
    nm._hardlink_into(dest_dir, source, log=lambda _msg: None)
    assert target.stat().st_ino == source.stat().st_ino


def test_deploy_native_mod_archive_success(tmp_path):
    archive_path = tmp_path / "MyMod.zip"
    _make_zip(archive_path, {"MyMod.dll": "binary-content"})
    managed_native_dir = tmp_path / "native_managed"
    managed_dir = tmp_path / "managed"
    logs: list[str] = []

    count = nm.deploy_native_mod_archive(
        archive_path,
        "Installation BG3/bin/NativeMods",
        managed_native_dir=managed_native_dir,
        managed_dir=managed_dir,
        log=logs.append,
    )
    assert count == 1
    dest = managed_dir / "Installation BG3" / "bin" / "NativeMods" / "MyMod.dll"
    assert dest.is_file()


def test_deploy_native_mod_archive_empty_raises(tmp_path):
    archive_path = tmp_path / "Empty.zip"
    with zipfile.ZipFile(archive_path, "w"):
        pass
    with pytest.raises(ArchiveError, match="vide"):
        nm.deploy_native_mod_archive(
            archive_path,
            "dest",
            managed_native_dir=tmp_path / "native",
            managed_dir=tmp_path / "managed",
        )


def test_deploy_native_mod_archive_removes_stale_extract_dir(tmp_path):
    archive_path = tmp_path / "MyMod.zip"
    _make_zip(archive_path, {"MyMod.dll": "content"})
    managed_native_dir = tmp_path / "native_managed"
    stale_extract_dir = managed_native_dir / "MyMod"
    stale_extract_dir.mkdir(parents=True)
    (stale_extract_dir / "leftover.txt").write_text("old")

    nm.deploy_native_mod_archive(
        archive_path,
        "dest",
        managed_native_dir=managed_native_dir,
        managed_dir=tmp_path / "managed",
    )
    assert not (stale_extract_dir / "leftover.txt").exists()


def test_deploy_native_mods_from_manifest_empty(tmp_path):
    report = nm.deploy_native_mods_from_manifest(
        pending_dir=tmp_path / "pending",
        installed_dir=tmp_path / "installed",
        managed_native_dir=tmp_path / "native",
        managed_dir=tmp_path / "managed",
        manifest_path=tmp_path / "manifest.json",
    )
    assert report == {"deployed": [], "skipped": [], "failed": []}


def test_deploy_native_mods_from_manifest_missing_and_never_deployed(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"Missing.zip": "dest"}))
    pending_dir = tmp_path / "pending"
    installed_dir = tmp_path / "installed"
    pending_dir.mkdir()

    report = nm.deploy_native_mods_from_manifest(
        pending_dir=pending_dir,
        installed_dir=installed_dir,
        managed_native_dir=tmp_path / "native",
        managed_dir=tmp_path / "managed",
        manifest_path=manifest_path,
    )
    assert report["skipped"] == ["Missing.zip"]


def test_deploy_native_mods_from_manifest_already_deployed(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"Already.zip": "dest"}))
    pending_dir = tmp_path / "pending"
    installed_dir = tmp_path / "installed"
    pending_dir.mkdir()
    installed_dir.mkdir()
    (installed_dir / "Already.zip").write_text("")

    report = nm.deploy_native_mods_from_manifest(
        pending_dir=pending_dir,
        installed_dir=installed_dir,
        managed_native_dir=tmp_path / "native",
        managed_dir=tmp_path / "managed",
        manifest_path=manifest_path,
    )
    assert report["skipped"] == ["Already.zip"]


def test_deploy_native_mods_from_manifest_failure(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"Bad.zip": "../escape"}))
    pending_dir = tmp_path / "pending"
    pending_dir.mkdir()
    _make_zip(pending_dir / "Bad.zip", {"file.dll": "x"})

    report = nm.deploy_native_mods_from_manifest(
        pending_dir=pending_dir,
        installed_dir=tmp_path / "installed",
        managed_native_dir=tmp_path / "native",
        managed_dir=tmp_path / "managed",
        manifest_path=manifest_path,
    )
    assert len(report["failed"]) == 1
    assert report["failed"][0][0] == "Bad.zip"


def test_deploy_native_mods_from_manifest_success_moves_archive(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"Good.zip": "dest"}))
    pending_dir = tmp_path / "pending"
    installed_dir = tmp_path / "installed"
    pending_dir.mkdir()
    _make_zip(pending_dir / "Good.zip", {"file.dll": "x"})

    report = nm.deploy_native_mods_from_manifest(
        pending_dir=pending_dir,
        installed_dir=installed_dir,
        managed_native_dir=tmp_path / "native",
        managed_dir=tmp_path / "managed",
        manifest_path=manifest_path,
    )
    assert report["deployed"] == ["Good.zip"]
    assert (installed_dir / "Good.zip").is_file()
    assert not (pending_dir / "Good.zip").exists()
