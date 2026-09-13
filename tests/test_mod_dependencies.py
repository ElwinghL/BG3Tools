"""Tests de `mod_dependencies.find_missing_dependencies` — voir ce module
pour le contexte (dépendances déclarées dans `meta.lsx` vs mods
effectivement présents ; incompatibilités volontairement hors scope,
décision explicite d'Elwingh : "Ignorons les incompatibilites mais
verifions les dependences")."""

from __future__ import annotations

from bg3_mod_tui.mod_dependencies import count_dependency_declarations, find_missing_dependencies
from bg3_mod_tui.pak_metadata import ModuleMetadata


def test_no_dependencies_declared_is_never_missing() -> None:
    mods = {
        "aaa": ModuleMetadata(uuid="aaa", name="Mod A", dependencies=()),
    }
    assert find_missing_dependencies(mods) == {}


def test_dependency_present_among_deployed_mods_is_not_missing() -> None:
    mods = {
        "aaa": ModuleMetadata(uuid="aaa", name="Mod A", dependencies=(("bbb", "Mod B"),)),
        "bbb": ModuleMetadata(uuid="bbb", name="Mod B", dependencies=()),
    }
    assert find_missing_dependencies(mods) == {}


def test_dependency_on_unknown_mod_is_reported_missing() -> None:
    mods = {
        "aaa": ModuleMetadata(
            uuid="aaa", name="Mod A", dependencies=(("zzz", "Mod Manquant"),)
        ),
    }
    assert find_missing_dependencies(mods) == {"Mod A": [("zzz", "Mod Manquant")]}


def test_vanilla_module_dependency_by_uuid_is_not_missing() -> None:
    mods = {
        "aaa": ModuleMetadata(
            uuid="aaa",
            name="Mod A",
            dependencies=(("28ac9ce2-2aba-8cda-b3b5-6e922f71b6b8", "GustavDev"),),
        ),
    }
    assert find_missing_dependencies(mods) == {}


def test_vanilla_module_dependency_by_name_is_not_missing() -> None:
    # "Gustav"/"Shared" n'ont pas d'UUID vérifié dans le catalogue (voir
    # Bg3SystemModules.cs) : reconnus par nom uniquement.
    mods = {
        "aaa": ModuleMetadata(
            uuid="aaa",
            name="Mod A",
            dependencies=(("00000000-0000-0000-0000-000000000000", "Shared"),),
        ),
    }
    assert find_missing_dependencies(mods) == {}


def test_mod_name_falls_back_to_uuid_when_empty() -> None:
    mods = {
        "aaa": ModuleMetadata(uuid="aaa", name="", dependencies=(("zzz", "Mod Manquant"),)),
    }
    assert find_missing_dependencies(mods) == {"aaa": [("zzz", "Mod Manquant")]}


def test_count_dependency_declarations_counts_distinct_mods() -> None:
    mods = {
        "aaa": ModuleMetadata(uuid="aaa", name="Mod A", dependencies=(("zzz", "Commun"),)),
        "bbb": ModuleMetadata(
            uuid="bbb", name="Mod B", dependencies=(("zzz", "Commun"), ("yyy", "Rare"))
        ),
        "ccc": ModuleMetadata(uuid="ccc", name="Mod C", dependencies=(("zzz", "Commun"),)),
    }
    counts = count_dependency_declarations(mods)
    assert counts["zzz"] == 3
    assert counts["yyy"] == 1


def test_multiple_missing_dependencies_all_reported() -> None:
    mods = {
        "aaa": ModuleMetadata(
            uuid="aaa",
            name="Mod A",
            dependencies=(("zzz", "Manquant 1"), ("yyy", "Manquant 2")),
        ),
    }
    assert find_missing_dependencies(mods) == {
        "Mod A": [("zzz", "Manquant 1"), ("yyy", "Manquant 2")]
    }
