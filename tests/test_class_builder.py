"""Tests du planificateur de build classe/sous-classe (TODO P3/10) :
règle de « progression continue vs nouveau choix » (`validate_build`),
cohérence structurelle des données (`class_data.CLASSES`), et génération
de la page HTML autonome (`generate_html`) — sans navigateur, la logique
JS embarquée étant une simple copie miroir de ce module Python."""

from __future__ import annotations

import json

from bg3_mod_tui.class_builder import (
    MAX_LEVEL,
    MIN_LEVEL,
    LevelChoice,
    build_report,
    generate_html,
    validate_build,
)
from bg3_mod_tui.class_data import CLASSES, GENERIC_FEATURE_FALLBACK, class_names, get_level_features


def _linear_fighter_build(n_levels: int) -> list[LevelChoice]:
    return [LevelChoice(level=lvl, class_name="Fighter") for lvl in range(1, n_levels + 1)]


def test_validate_build_liste_vide_est_valide():
    assert validate_build([]) == []


def test_validate_build_progression_simple_sans_erreur():
    choices = [
        LevelChoice(1, "Fighter"),
        LevelChoice(2, "Fighter"),
        LevelChoice(3, "Fighter", "Battle Master"),
        LevelChoice(4, "Fighter"),
    ]
    assert validate_build(choices) == []


def test_validate_build_continuation_illimitee_sans_erreur():
    # Rester sur la même classe jusqu'au niveau 20 doit toujours être valide.
    assert validate_build(_linear_fighter_build(MAX_LEVEL)) == []


def test_validate_build_changement_de_classe_autorise_une_seule_fois():
    choices = [
        LevelChoice(1, "Fighter"),
        LevelChoice(2, "Wizard", "Evocation"),
    ]
    assert validate_build(choices) == []


def test_validate_build_refuse_de_reprendre_une_classe_deja_quittee():
    choices = [
        LevelChoice(1, "Fighter"),
        LevelChoice(2, "Fighter"),
        LevelChoice(3, "Wizard", "Evocation"),
        LevelChoice(4, "Fighter"),  # reprise de Fighter -> interdit
    ]
    errors = validate_build(choices)
    assert len(errors) == 1
    assert "Fighter" in errors[0]
    assert "niveau 4" in errors[0].lower() or "Niveau 4" in errors[0]


def test_validate_build_detecte_niveau_manquant():
    choices = [LevelChoice(1, "Fighter"), LevelChoice(3, "Fighter")]
    errors = validate_build(choices)
    assert any("Niveau 2" in e for e in errors)


def test_validate_build_detecte_classe_inconnue():
    errors = validate_build([LevelChoice(1, "ClasseInexistante")])
    assert any("classe inconnue" in e.lower() for e in errors)


def test_validate_build_sous_classe_avant_deblocage_est_une_erreur():
    # Fighter débloque sa sous-classe au niveau 3 : la choisir au niveau 1
    # doit être signalé.
    errors = validate_build([LevelChoice(1, "Fighter", "Battle Master")])
    assert any("déblocage" in e for e in errors)


def test_validate_build_refuse_le_changement_de_sous_classe():
    choices = [
        LevelChoice(1, "Fighter"),
        LevelChoice(2, "Fighter"),
        LevelChoice(3, "Fighter", "Battle Master"),
        LevelChoice(4, "Fighter", "Champion"),
    ]
    errors = validate_build(choices)
    assert any("sous-classe" in e for e in errors)


def test_validate_build_sous_classe_inconnue_est_une_erreur():
    errors = validate_build([LevelChoice(1, "Cleric", "SousClasseInexistante")])
    assert any("sous-classe inconnue" in e.lower() for e in errors)


def test_validate_build_multiclassage_realiste_barbare_puis_roublard():
    # Un multiclassage 5e classique : Barbare 1-5 puis Roublard 6-20, sans
    # jamais reprendre le Barbare -> doit rester valide.
    choices = _linear_fighter_build(0)  # liste vide, on construit à la main
    choices = [LevelChoice(lvl, "Barbarian", "Berserker" if lvl >= 3 else None) for lvl in range(1, 6)]
    choices += [LevelChoice(lvl, "Rogue", "Thief" if lvl >= 9 else None) for lvl in range(6, 21)]
    assert validate_build(choices) == []


def test_class_data_classes_couvre_les_douze_classes_de_base_bg3():
    attendu = {
        "Barbarian",
        "Bard",
        "Cleric",
        "Druid",
        "Fighter",
        "Monk",
        "Paladin",
        "Ranger",
        "Rogue",
        "Sorcerer",
        "Warlock",
        "Wizard",
    }
    assert set(CLASSES) == attendu


def test_class_data_chaque_classe_a_une_structure_complete():
    for name, info in CLASSES.items():
        assert isinstance(info.get("fr"), str) and info["fr"], name
        assert MIN_LEVEL <= info["subclass_unlock_level"] <= MAX_LEVEL, name
        assert isinstance(info.get("subclasses"), dict) and info["subclasses"], name
        for sub_name, sub in info["subclasses"].items():
            assert isinstance(sub.get("fr"), str) and sub["fr"], (name, sub_name)


def test_class_names_est_trie_et_couvre_toutes_les_classes():
    assert class_names() == sorted(CLASSES)


def test_get_level_features_retourne_repli_generique_si_classe_inconnue():
    assert get_level_features("Inexistante", 1) == [GENERIC_FEATURE_FALLBACK]


def test_get_level_features_inclut_le_choix_de_sous_classe_au_niveau_de_deblocage():
    feats = get_level_features("Fighter", 3, "Battle Master")
    assert any("sous-classe" in f.lower() for f in feats)


def test_get_level_features_ajoute_amelioration_caracteristique_aux_paliers_asi():
    feats = get_level_features("Fighter", 4, None)
    assert any("Amélioration" in f for f in feats)


def test_build_report_reflete_la_sous_classe_active_sur_toute_la_continuation():
    choices = [
        LevelChoice(1, "Fighter"),
        LevelChoice(2, "Fighter"),
        LevelChoice(3, "Fighter", "Battle Master"),
        LevelChoice(4, "Fighter"),
    ]
    report = build_report(choices)
    assert [entry["level"] for entry in report] == [1, 2, 3, 4]
    assert report[0]["subclass_name"] is None
    assert report[2]["subclass_name"] == "Battle Master"
    # La sous-classe reste active aux niveaux suivants de la même classe,
    # sans avoir à être re-choisie.
    assert report[3]["subclass_name"] == "Battle Master"


def test_generate_html_est_autonome_et_bien_forme():
    html = generate_html()
    assert "__CLASS_DATA_JSON__" not in html
    assert "__MIN_LEVEL__" not in html
    assert "__MAX_LEVEL__" not in html
    assert html.startswith("<!doctype html>")
    assert html.count("<html") == 1
    assert html.count("</html>") == 1
    # Le JSON des données de classes doit être injecté et valide.
    start = html.index("const CLASS_DATA = ") + len("const CLASS_DATA = ")
    end = html.index(";\n", start)
    payload = json.loads(html[start:end])
    assert set(payload) == set(CLASSES)


def test_generate_html_mentionne_mermaid_et_le_repli_hors_ligne():
    html = generate_html()
    assert "mermaid" in html.lower()
    assert "hors ligne" in html.lower() or "mermaid-source" in html
