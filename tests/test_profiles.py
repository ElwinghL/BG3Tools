"""Tests de `bg3_mod_tui.profiles` : `slugify_profile_name` (conversion en
nom de dossier sûr) et `manifest_file_names` (extraction des noms de
fichiers, compatible ancien/nouveau format de manifeste)."""

from __future__ import annotations

import pytest

from bg3_mod_tui.profiles import ProfileError, manifest_file_names, slugify_profile_name


def test_slugify_nom_simple_alphanumerique_est_inchange():
    assert slugify_profile_name("MonProfil") == "MonProfil"


def test_slugify_remplace_les_espaces_et_caracteres_speciaux():
    # Les underscores de bordure sont ensuite retirés (voir
    # `test_slugify_supprime_les_underscores_de_bordure`), d'où l'absence
    # de "_" final malgré le "!" en fin de chaîne.
    assert slugify_profile_name("Mon Profil #1 !") == "Mon_Profil_1"


def test_slugify_conserve_underscore_et_tiret():
    assert slugify_profile_name("mon-profil_v2") == "mon-profil_v2"


def test_slugify_supprime_les_underscores_de_bordure():
    assert slugify_profile_name("  ***Profil***  ") == "Profil"


def test_slugify_nom_vide_leve_profile_error():
    with pytest.raises(ProfileError):
        slugify_profile_name("")


def test_slugify_nom_uniquement_special_leve_profile_error():
    with pytest.raises(ProfileError):
        slugify_profile_name("!!!")


def test_manifest_file_names_ancien_format_liste_de_noms():
    entries = ["ModA.pak", "ModB.pak"]
    assert manifest_file_names(entries) == {"ModA.pak", "ModB.pak"}


def test_manifest_file_names_nouveau_format_liste_de_dicts():
    entries = [
        {"file": "ModA.pak", "origin": {"nexus_mod_id": 42}},
        {"file": "ModB.pak", "origin": None},
    ]
    assert manifest_file_names(entries) == {"ModA.pak", "ModB.pak"}


def test_manifest_file_names_format_mixte():
    entries = ["ModA.pak", {"file": "ModB.pak", "origin": None}]
    assert manifest_file_names(entries) == {"ModA.pak", "ModB.pak"}


def test_manifest_file_names_liste_vide():
    assert manifest_file_names([]) == set()
