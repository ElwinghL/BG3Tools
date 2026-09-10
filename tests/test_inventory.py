"""Tests de `bg3_mod_tui.inventory.known_mod_ids` : détection des ID Nexus
déjà présents (sous forme d'archive) dans un ou plusieurs dossiers, à
partir du nom de fichier (convention de téléchargement navigateur/API)."""

from __future__ import annotations

from bg3_mod_tui.inventory import known_mod_ids

# Nom d'archive suivant la convention navigateur/API Nexus :
# "<nom>-<id>-<version>-<timestamp 10 chiffres>.<ext>".
_BROWSER_NAME = "MonMod-1234-1-2-0-1690000000.zip"


def test_known_mod_ids_dossier_vide(tmp_path):
    assert known_mod_ids(tmp_path) == set()


def test_known_mod_ids_dossier_inexistant_est_ignore(tmp_path):
    assert known_mod_ids(tmp_path / "n_existe_pas") == set()


def test_known_mod_ids_detecte_un_id_dans_un_seul_dossier(tmp_path):
    (tmp_path / _BROWSER_NAME).write_bytes(b"contenu")
    assert known_mod_ids(tmp_path) == {1234}


def test_known_mod_ids_ignore_les_fichiers_sans_extension_archive(tmp_path):
    (tmp_path / "notes.txt").write_text("pas une archive")
    assert known_mod_ids(tmp_path) == set()


def test_known_mod_ids_ignore_les_noms_ne_suivant_aucune_convention(tmp_path):
    (tmp_path / "archive_github.zip").write_bytes(b"contenu")
    assert known_mod_ids(tmp_path) == set()


def test_known_mod_ids_agrege_plusieurs_dossiers(tmp_path):
    dir_a = tmp_path / "a_traiter"
    dir_b = tmp_path / "_installees"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "ModA-1111-1-0-1690000000.zip").write_bytes(b"x")
    (dir_b / "ModB-2222-1-0-1690000001.zip").write_bytes(b"x")

    assert known_mod_ids(dir_a, dir_b) == {1111, 2222}


def test_known_mod_ids_meme_id_present_dans_deux_dossiers_ne_compte_qu_une_fois(tmp_path):
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "ModA-3333-1-0-1690000000.zip").write_bytes(b"x")
    (dir_b / "ModA-3333-2-0-1690000005.zip").write_bytes(b"x")

    ids = known_mod_ids(dir_a, dir_b)
    assert ids == {3333}
