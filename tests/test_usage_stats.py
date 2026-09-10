"""Tests de `bg3_mod_tui.usage_stats` : compteur persistant d'utilisation
par bouton d'action (profil) et calcul du top des quick actions —
équivalent JSON par profil au style de `profiles.load_blacklisted_files`,
testable ici sans monter l'UI Textual (voir `tmp_path`)."""

from __future__ import annotations

from bg3_mod_tui.usage_stats import (
    USAGE_STATS_FILENAME,
    increment_usage_stat,
    load_usage_stats,
    save_usage_stats,
    top_actions,
)


def test_load_usage_stats_fichier_absent_retourne_dict_vide(tmp_path):
    assert load_usage_stats(tmp_path, "MonProfil") == {}


def test_load_usage_stats_fichier_corrompu_retourne_dict_vide(tmp_path):
    profile_dir = tmp_path / "MonProfil"
    profile_dir.mkdir(parents=True)
    (profile_dir / USAGE_STATS_FILENAME).write_text("{pas du json", encoding="utf-8")
    assert load_usage_stats(tmp_path, "MonProfil") == {}


def test_load_usage_stats_contenu_non_dict_retourne_dict_vide(tmp_path):
    profile_dir = tmp_path / "MonProfil"
    profile_dir.mkdir(parents=True)
    (profile_dir / USAGE_STATS_FILENAME).write_text("[1, 2, 3]", encoding="utf-8")
    assert load_usage_stats(tmp_path, "MonProfil") == {}


def test_save_puis_load_usage_stats_aller_retour(tmp_path):
    save_usage_stats(tmp_path, "MonProfil", {"action-extract": 3, "action-tools": 1})
    assert load_usage_stats(tmp_path, "MonProfil") == {
        "action-extract": 3,
        "action-tools": 1,
    }


def test_increment_usage_stat_cree_le_compteur_a_1(tmp_path):
    stats = increment_usage_stat(tmp_path, "MonProfil", "action-extract")
    assert stats == {"action-extract": 1}
    assert load_usage_stats(tmp_path, "MonProfil") == {"action-extract": 1}


def test_increment_usage_stat_incremente_un_compteur_existant(tmp_path):
    increment_usage_stat(tmp_path, "MonProfil", "action-extract")
    increment_usage_stat(tmp_path, "MonProfil", "action-extract")
    stats = increment_usage_stat(tmp_path, "MonProfil", "action-extract")
    assert stats == {"action-extract": 3}


def test_increment_usage_stat_suit_plusieurs_boutons_independamment(tmp_path):
    increment_usage_stat(tmp_path, "MonProfil", "action-extract")
    increment_usage_stat(tmp_path, "MonProfil", "action-tools")
    stats = increment_usage_stat(tmp_path, "MonProfil", "action-extract")
    assert stats == {"action-extract": 2, "action-tools": 1}


def test_increment_usage_stat_isole_par_profil(tmp_path):
    increment_usage_stat(tmp_path, "ProfilA", "action-extract")
    increment_usage_stat(tmp_path, "ProfilB", "action-extract")
    increment_usage_stat(tmp_path, "ProfilA", "action-extract")
    assert load_usage_stats(tmp_path, "ProfilA") == {"action-extract": 2}
    assert load_usage_stats(tmp_path, "ProfilB") == {"action-extract": 1}


def test_top_actions_trie_par_compteur_decroissant():
    stats = {"action-a": 1, "action-b": 5, "action-c": 3, "action-d": 2}
    assert top_actions(stats) == ["action-b", "action-c", "action-d"]


def test_top_actions_limite_configurable():
    stats = {"action-a": 1, "action-b": 5, "action-c": 3}
    assert top_actions(stats, limit=1) == ["action-b"]
    assert top_actions(stats, limit=2) == ["action-b", "action-c"]


def test_top_actions_egalite_departagee_par_ordre_alphabetique_de_l_id():
    stats = {"action-zebre": 2, "action-abeille": 2, "action-lion": 2}
    assert top_actions(stats) == ["action-abeille", "action-lion", "action-zebre"]


def test_top_actions_ignore_les_compteurs_a_zero():
    stats = {"action-a": 0, "action-b": 1}
    assert top_actions(stats) == ["action-b"]


def test_top_actions_dict_vide_retourne_liste_vide():
    assert top_actions({}) == []


def test_top_actions_moins_de_limit_boutons_disponibles():
    stats = {"action-a": 4}
    assert top_actions(stats, limit=3) == ["action-a"]
