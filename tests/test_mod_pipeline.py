"""Tests de `bg3_mod_tui.mod_pipeline` : `_unique_destination` (évite
d'écraser un fichier existant en suffixant "(1)", "(2)"...) et
`extract_archives_to_mods` sur un cas simple avec de vraies archives .zip
temporaires (dédup des .pak déjà présents dans `mods_dir`)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from bg3_mod_tui.mod_pipeline import _unique_destination, extract_archives_to_mods


def _make_zip(path: Path, *entries: tuple[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries:
            zf.writestr(name, content)


def test_unique_destination_nom_disponible_reste_inchange(tmp_path):
    dest = _unique_destination(tmp_path, "mod.zip")
    assert dest == tmp_path / "mod.zip"
    assert not dest.exists()


def test_unique_destination_cree_le_dossier_de_destination(tmp_path):
    dest_dir = tmp_path / "sous_dossier"
    dest = _unique_destination(dest_dir, "mod.zip")
    assert dest_dir.is_dir()
    assert dest == dest_dir / "mod.zip"


def test_unique_destination_nom_deja_pris_suffixe_1(tmp_path):
    (tmp_path / "mod.zip").write_bytes(b"contenu existant")
    dest = _unique_destination(tmp_path, "mod.zip")
    assert dest == tmp_path / "mod (1).zip"


def test_unique_destination_plusieurs_collisions_incrementent_le_suffixe(tmp_path):
    (tmp_path / "mod.zip").write_bytes(b"a")
    (tmp_path / "mod (1).zip").write_bytes(b"b")
    (tmp_path / "mod (2).zip").write_bytes(b"c")
    dest = _unique_destination(tmp_path, "mod.zip")
    assert dest == tmp_path / "mod (3).zip"


def test_unique_destination_preserve_l_extension(tmp_path):
    (tmp_path / "archive.tar.zip").write_bytes(b"a")
    dest = _unique_destination(tmp_path, "archive.tar.zip")
    assert dest.suffix == ".zip"
    assert dest.name == "archive.tar (1).zip"


def _make_pipeline_dirs(tmp_path: Path) -> dict[str, Path]:
    dirs = {
        "archives_dir": tmp_path / "a_traiter",
        "mods_dir": tmp_path / "Mods",
        "pending_dir": tmp_path / "_a_traiter",
        "installed_dir": tmp_path / "_installees",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def test_extract_archives_to_mods_installe_un_pak_simple(tmp_path):
    dirs = _make_pipeline_dirs(tmp_path)
    _make_zip(dirs["archives_dir"] / "MonMod.zip", ("MonMod.pak", b"donnees pak"))

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert report["installed"] == ["MonMod.zip"]
    assert report["pending"] == []
    assert report["failed"] == []
    assert (dirs["mods_dir"] / "MonMod.pak").is_file()
    assert (dirs["installed_dir"] / "MonMod.zip").is_file()
    assert not (dirs["archives_dir"] / "MonMod.zip").exists()


def test_extract_archives_to_mods_dedup_pak_deja_present(tmp_path):
    # Le .pak "MonMod.pak" est déjà dans mods_dir (ex: extrait d'un
    # précédent passage) : l'extraction d'une nouvelle archive fournissant
    # un .pak de même nom ne doit pas l'écraser mais créer "MonMod (1).pak".
    dirs = _make_pipeline_dirs(tmp_path)
    (dirs["mods_dir"] / "MonMod.pak").write_bytes(b"ancienne version")
    _make_zip(dirs["archives_dir"] / "MonMod-update.zip", ("MonMod.pak", b"nouvelle version"))

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert report["installed"] == ["MonMod-update.zip"]
    assert (dirs["mods_dir"] / "MonMod.pak").read_bytes() == b"ancienne version"
    assert (dirs["mods_dir"] / "MonMod (1).pak").read_bytes() == b"nouvelle version"


def test_extract_archives_to_mods_archive_sans_pak_ni_dossier_connu_va_en_examen(tmp_path):
    dirs = _make_pipeline_dirs(tmp_path)
    _make_zip(dirs["archives_dir"] / "Inconnu.zip", ("lisez-moi.txt", b"rien d'utile"))

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert report["pending"] == ["Inconnu.zip"]
    assert report["installed"] == []
    assert (dirs["pending_dir"] / "Inconnu.zip").is_file()


def test_extract_archives_to_mods_archive_corrompue_est_signalee_en_echec(tmp_path):
    dirs = _make_pipeline_dirs(tmp_path)
    bad = dirs["archives_dir"] / "Corrompu.zip"
    bad.write_bytes(b"pas un vrai zip")

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert len(report["failed"]) == 1
    assert report["failed"][0][0] == "Corrompu.zip"
    assert (dirs["pending_dir"] / "Corrompu.zip").is_file()
