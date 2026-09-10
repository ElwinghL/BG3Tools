"""Tests de `bg3_mod_tui.versioning` : extraction/comparaison de versions
de mods (formats hétérogènes Nexus/mod.io, voir docstring du module)."""

from __future__ import annotations

from bg3_mod_tui.versioning import is_newer, parse_version, select_priority_source


def test_parse_version_extrait_les_composants_numeriques():
    assert parse_version("1.12.3") == (1, 12, 3)


def test_parse_version_ignore_le_texte_autour():
    assert parse_version("v1.2-beta") == (1, 2)


def test_parse_version_gere_les_tirets_nexus():
    assert parse_version("1-2-3") == (1, 2, 3)


def test_parse_version_vide_ou_none():
    assert parse_version("") == ()
    assert parse_version(None) == ()


def test_parse_version_texte_sans_chiffre():
    assert parse_version("Release Candidate") == ()


def test_is_newer_version_majeure_superieure():
    assert is_newer("2.0", "1.9.9") is True


def test_is_newer_ne_confond_pas_longueur_et_valeur():
    # "1.2" doit être plus récent que "1.1.9" (comparaison position par
    # position avec complétion à 0), pas trompé par sa longueur plus courte.
    assert is_newer("1.2", "1.1.9") is True


def test_is_newer_version_egale_n_est_pas_plus_recente():
    assert is_newer("1.2.0", "1.2") is False
    assert is_newer("1.2", "1.2") is False


def test_is_newer_version_anterieure():
    assert is_newer("1.0", "1.1") is False


def test_is_newer_pas_de_tri_alphabetique_naif():
    # "9" ne doit pas être vu comme plus récent que "10" (piège classique
    # d'une comparaison de chaînes brute).
    assert is_newer("9", "10") is False
    assert is_newer("10", "9") is True


def test_is_newer_version_illisible_retourne_false():
    assert is_newer("build-final", "1.0") is False
    assert is_newer("1.0", "build-final") is False
    assert is_newer(None, "1.0") is False
    assert is_newer("1.0", None) is False


def test_select_priority_source_modio_plus_recent():
    assert select_priority_source("1.0", "2.0") == "modio"


def test_select_priority_source_nexus_plus_recent_ou_egal():
    assert select_priority_source("2.0", "1.0") == "nexus"
    assert select_priority_source("1.0", "1.0") == "nexus"


def test_select_priority_source_version_modio_illisible_reste_nexus():
    # Dans le doute (version mod.io absente/illisible), on ne bascule
    # jamais vers mod.io.
    assert select_priority_source("1.0", None) == "nexus"
    assert select_priority_source("1.0", "") == "nexus"
