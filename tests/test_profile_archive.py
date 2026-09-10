"""Tests de `bg3_mod_tui.profile_archive` : garde-fou de version de
l'outil (embarquée à l'export, comparée à l'import) et signalement des
fichiers du manifeste absents de l'archive à l'import — les deux en mode
avertissement (import best-effort), pas en échec bloquant, cohérent avec
le reste du module (fichier absent à l'export déjà seulement journalisé)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import zstandard

from bg3_mod_tui import __version__ as TOOL_VERSION
from bg3_mod_tui.profile_archive import (
    TOOL_VERSION_ARCNAME,
    export_profile_archive,
    import_profile_archive,
)
from bg3_mod_tui.profiles import MANIFEST_FILENAME, MODSETTINGS_FILENAME


def _make_profile_dir(profiles_dir: Path, name: str, manifest: dict) -> None:
    profile_dir = profiles_dir / name
    profile_dir.mkdir(parents=True)
    (profile_dir / MODSETTINGS_FILENAME).write_text("<save/>", encoding="utf-8")
    (profile_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")


def _export(tmp_path: Path, manifest: dict, *, create_paks: list[str]) -> tuple[Path, list[str]]:
    profiles_dir = tmp_path / "profiles"
    mods_dir = tmp_path / "Mods"
    mods_dir.mkdir()
    for pak in create_paks:
        (mods_dir / pak).write_bytes(b"fake-pak")
    loose_mods_dir = tmp_path / "DataMods"
    loose_mods_dir.mkdir()
    native_mods_dir = tmp_path / "NativeMods"
    native_mods_dir.mkdir()

    _make_profile_dir(profiles_dir, "MonProfil", manifest)

    logs: list[str] = []
    dest_path = tmp_path / "MonProfil.bg3profile.tar.zst"
    export_profile_archive(
        "MonProfil",
        profiles_dir=profiles_dir,
        mods_dir=mods_dir,
        loose_mods_dir=loose_mods_dir,
        native_mods_dir=native_mods_dir,
        dest_path=dest_path,
        log=logs.append,
    )
    return dest_path, logs


def _import(tmp_path: Path, archive_path: Path, *, subdir: str = "import") -> tuple[str, list[str]]:
    base = tmp_path / subdir
    logs: list[str] = []
    name = import_profile_archive(
        archive_path,
        profiles_dir=base / "profiles",
        mods_dir=base / "Mods",
        loose_mods_dir=base / "DataMods",
        native_mods_dir=base / "NativeMods",
        log=logs.append,
    )
    return name, logs


def _read_tar_bytes(archive_path: Path) -> bytes:
    decompressor = zstandard.ZstdDecompressor()
    with archive_path.open("rb") as raw, decompressor.stream_reader(raw) as zfh:
        return zfh.read()


def _write_tar_bytes(archive_path: Path, tar_bytes: bytes) -> None:
    compressor = zstandard.ZstdCompressor(level=3)
    archive_path.write_bytes(compressor.compress(tar_bytes))


def _rewrite_tool_version(archive_path: Path, dest: Path, data: dict | None) -> None:
    """Recrée `archive_path` sous `dest` en remplaçant (ou supprimant si
    `data` est None) le membre `tool_version.json` — simule une archive
    créée par une autre version de l'outil, ou par une version antérieure
    à l'ajout de ce garde-fou (archive sans ce fichier du tout)."""
    import tarfile

    tar_bytes = _read_tar_bytes(archive_path)
    out_buf = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tin, \
            tarfile.open(fileobj=out_buf, mode="w:") as tout:
        for member in tin.getmembers():
            if member.name == TOOL_VERSION_ARCNAME:
                if data is None:
                    continue
                encoded = json.dumps(data).encode("utf-8")
                info = tarfile.TarInfo(TOOL_VERSION_ARCNAME)
                info.size = len(encoded)
                tout.addfile(info, io.BytesIO(encoded))
            else:
                fh = tin.extractfile(member)
                tout.addfile(member, fh)
    _write_tar_bytes(dest, out_buf.getvalue())


def test_export_embarque_la_version_de_loutil(tmp_path):
    archive_path, _logs = _export(tmp_path, {"name": "MonProfil", "paks": [], "native_mods": [], "loose_files": []}, create_paks=[])
    tar_bytes = _read_tar_bytes(archive_path)
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
        member = tar.getmember(TOOL_VERSION_ARCNAME)
        data = json.loads(tar.extractfile(member).read())
    assert data == {"tool_version": TOOL_VERSION}


def test_import_version_identique_nemet_aucun_avertissement(tmp_path):
    archive_path, _ = _export(tmp_path, {"name": "MonProfil", "paks": [], "native_mods": [], "loose_files": []}, create_paks=[])
    name, logs = _import(tmp_path, archive_path)
    assert name == "MonProfil"
    assert not any("version" in msg.lower() for msg in logs)


def test_import_version_differente_avertit_mais_importe(tmp_path):
    archive_path, _ = _export(tmp_path, {"name": "MonProfil", "paks": [], "native_mods": [], "loose_files": []}, create_paks=[])
    modified = tmp_path / "modified.bg3profile.tar.zst"
    _rewrite_tool_version(archive_path, modified, {"tool_version": "0.0.1-autre"})

    name, logs = _import(tmp_path, modified)

    assert name == "MonProfil"
    assert any("0.0.1-autre" in msg for msg in logs)
    assert any(TOOL_VERSION in msg for msg in logs)


def test_import_version_absente_geree_sans_planter(tmp_path):
    archive_path, _ = _export(tmp_path, {"name": "MonProfil", "paks": [], "native_mods": [], "loose_files": []}, create_paks=[])
    old_style = tmp_path / "old_style.bg3profile.tar.zst"
    _rewrite_tool_version(archive_path, old_style, None)

    name, logs = _import(tmp_path, old_style)

    assert name == "MonProfil"
    assert any("inconnue" in msg.lower() for msg in logs)


def test_import_signale_les_fichiers_du_manifeste_absents_de_larchive(tmp_path):
    # ModB.pak est listé au manifeste mais jamais créé dans Mods/ : l'export
    # l'exclut donc déjà de l'archive (comportement existant, journalisé),
    # ce qui reproduit exactement une archive incomplète pour l'import.
    manifest = {
        "name": "MonProfil",
        "paks": ["ModA.pak", "ModB.pak"],
        "native_mods": [],
        "loose_files": [],
    }
    archive_path, export_logs = _export(tmp_path, manifest, create_paks=["ModA.pak"])
    assert any("ModB.pak" in msg for msg in export_logs)

    name, logs = _import(tmp_path, archive_path)

    assert name == "MonProfil"
    assert any("ModB.pak" in msg and "incomplète" in msg for msg in logs)
    # Le fichier présent est bien copié malgré l'avertissement sur l'absent.
    assert (tmp_path / "import" / "Mods" / "ModA.pak").is_file()
    assert not (tmp_path / "import" / "Mods" / "ModB.pak").is_file()


def test_import_archive_complete_naucun_avertissement_de_completude(tmp_path):
    manifest = {"name": "MonProfil", "paks": ["ModA.pak"], "native_mods": [], "loose_files": []}
    archive_path, _ = _export(tmp_path, manifest, create_paks=["ModA.pak"])

    _name, logs = _import(tmp_path, archive_path)

    assert not any("incomplète" in msg for msg in logs)
