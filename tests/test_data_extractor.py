"""Tests de `bg3_mod_tui.data_extractor` (TODO.md section 16) : détection
best-effort de mentions de classes/sous-classes/dons/objets dans la
description Nexus d'un mod (16a), construction de la documentation à
partir d'un inventaire (`mods_inventory.json`), sérialisation JSON (16c),
et extraction réelle de dons/objets depuis le contenu d'un .pak SYNTHÉTIQUE
(16b — pas de vrai .pak BG3 disponible dans cet environnement de test)."""

from __future__ import annotations

import json

import pytest

from bg3_mod_tui.data_extractor import (
    EntityMention,
    ModDocumentation,
    PakEntity,
    StatsEntry,
    build_documentation_index,
    documentation_index_to_json,
    extract_pak_entities,
    parse_stats_entries,
    save_documentation_index,
    scan_entity_mentions,
)
from bg3_mod_tui.providers.nexus import NexusAPIError, NexusMod
from tests.test_pak_reader import _build_v18_pak_multi

# --- scan_entity_mentions ------------------------------------------------


def test_scan_entity_mentions_texte_vide():
    assert scan_entity_mentions("") == []
    assert scan_entity_mentions(None) == []  # type: ignore[arg-type]


def test_scan_entity_mentions_aucune_expression_reconnue():
    assert scan_entity_mentions("Ce mod corrige un bug d'affichage du HUD.") == []


def test_scan_entity_mentions_detecte_une_nouvelle_classe():
    mentions = scan_entity_mentions("Ce mod ajoute une nouvelle classe : le Chevalier runique.")
    assert mentions == [
        EntityMention(
            kind="classe",
            label="Ce mod ajoute une nouvelle classe : le Chevalier runique.",
            source="nexus_summary",
        )
    ]


def test_scan_entity_mentions_detecte_une_sous_classe_insensible_a_la_casse():
    mentions = scan_entity_mentions("Adds a NEW SUBCLASS for the Rogue.")
    assert len(mentions) == 1
    assert mentions[0].kind == "sous_classe"


def test_scan_entity_mentions_plusieurs_phrases_plusieurs_types():
    text = (
        "Ce mod ajoute une nouvelle sous-classe pour le Barde. "
        "Il ajoute aussi un nouvel objet légendaire. "
        "Rien d'autre à signaler ici."
    )
    mentions = scan_entity_mentions(text)
    kinds = sorted(m.kind for m in mentions)
    assert kinds == ["objet", "sous_classe"]


def test_scan_entity_mentions_deduplique_une_phrase_repetee():
    text = "Nouvel objet ajouté. Nouvel objet ajouté."
    mentions = scan_entity_mentions(text)
    assert len(mentions) == 1


def test_scan_entity_mentions_ne_matche_pas_les_mots_isoles_trop_communs():
    # "don" et "objet" seuls (sans l'expression multi-mots attendue) ne
    # doivent pas déclencher de faux positif — voir la docstring de
    # `_KEYWORDS` dans data_extractor.py.
    text = "Le don de ce mod à la communauté est un objet de fierté."
    assert scan_entity_mentions(text) == []


# --- build_documentation_index -------------------------------------------


def _inventory(paks: list[dict], archives: list[dict]) -> dict:
    return {"paks": paks, "archives": archives}


def test_build_documentation_index_inventaire_vide():
    assert build_documentation_index(_inventory([], [])) == []


def test_build_documentation_index_sans_archive_associee():
    inventory = _inventory(
        paks=[{"file": "ModSansOrigine.pak", "matched_archive": None}],
        archives=[],
    )
    entries = build_documentation_index(inventory)
    assert entries == [
        ModDocumentation(
            pak_file="ModSansOrigine.pak",
            mod_name="ModSansOrigine",
            nexus_mod_id=None,
            nexus_url=None,
            version=None,
            mentions=[],
        )
    ]


def test_build_documentation_index_avec_archive_mais_sans_client_nexus():
    inventory = _inventory(
        paks=[{"file": "MonMod.pak", "matched_archive": "MonMod-1234-1-0-1690000000.zip"}],
        archives=[
            {
                "file": "MonMod-1234-1-0-1690000000.zip",
                "nexus_mod_id": 1234,
                "nexus_url": "https://www.nexusmods.com/baldursgate3/mods/1234",
                "version": "1.0",
                "mod_name_guess": "Mon Mod",
            }
        ],
    )
    entries = build_documentation_index(inventory)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.mod_name == "Mon Mod"
    assert entry.nexus_mod_id == 1234
    assert entry.mentions == []  # pas de client Nexus fourni -> pas d'enrichissement


class _FakeNexusClient:
    """Double de `NexusClient` : pas d'appel réseau, juste un résumé ou une
    erreur préconfigurés par mod_id."""

    def __init__(self, by_id: dict[int, NexusMod | Exception]) -> None:
        self._by_id = by_id

    def mod_info(self, mod_id: int) -> NexusMod:
        result = self._by_id[mod_id]
        if isinstance(result, Exception):
            raise result
        return result


def test_build_documentation_index_enrichit_avec_le_resume_nexus():
    inventory = _inventory(
        paks=[{"file": "MonMod.pak", "matched_archive": "MonMod-1234-1-0-1690000000.zip"}],
        archives=[
            {
                "file": "MonMod-1234-1-0-1690000000.zip",
                "nexus_mod_id": 1234,
                "nexus_url": "https://www.nexusmods.com/baldursgate3/mods/1234",
                "version": "1.0",
                "mod_name_guess": "Mon Mod",
            }
        ],
    )
    fake_client = _FakeNexusClient(
        {1234: NexusMod(mod_id=1234, name="Mon Mod", version="1.0", summary="Ajoute une nouvelle classe.")}
    )
    entries = build_documentation_index(inventory, nexus_client=fake_client)
    assert len(entries) == 1
    assert [m.kind for m in entries[0].mentions] == ["classe"]


def test_build_documentation_index_tolere_un_echec_nexus_pour_un_mod():
    inventory = _inventory(
        paks=[
            {"file": "ModA.pak", "matched_archive": "ModA-1-1-0-1690000000.zip"},
            {"file": "ModB.pak", "matched_archive": "ModB-2-1-0-1690000000.zip"},
        ],
        archives=[
            {"file": "ModA-1-1-0-1690000000.zip", "nexus_mod_id": 1, "mod_name_guess": "Mod A"},
            {"file": "ModB-2-1-0-1690000000.zip", "nexus_mod_id": 2, "mod_name_guess": "Mod B"},
        ],
    )
    fake_client = _FakeNexusClient(
        {
            1: NexusAPIError("Mod Nexus 1 introuvable (404)."),
            2: NexusMod(mod_id=2, name="Mod B", version="1.0", summary="Ajoute un nouvel objet."),
        }
    )
    progress_lines: list[str] = []
    entries = build_documentation_index(
        inventory, nexus_client=fake_client, on_progress=progress_lines.append
    )
    assert len(entries) == 2
    assert entries[0].mentions == []  # échec Nexus -> pas de mention, pas de crash
    assert [m.kind for m in entries[1].mentions] == ["objet"]
    assert any("indisponible" in line for line in progress_lines)


# --- documentation_index_to_json / save_documentation_index --------------


def test_documentation_index_to_json_regroupe_par_type_d_entite():
    entries = [
        ModDocumentation(
            pak_file="MonMod.pak",
            mod_name="Mon Mod",
            nexus_mod_id=1234,
            nexus_url="https://www.nexusmods.com/baldursgate3/mods/1234",
            version="1.0",
            mentions=[
                EntityMention(kind="classe", label="Nouvelle classe.", source="nexus_summary"),
                EntityMention(kind="objet", label="Nouvel objet.", source="nexus_summary"),
            ],
        )
    ]
    data = documentation_index_to_json(entries)
    assert "generated_at" in data
    assert len(data["classes"]) == 1
    assert data["classes"][0] == {
        "mod_name": "Mon Mod",
        "pak_file": "MonMod.pak",
        "nexus_mod_id": 1234,
        "nexus_url": "https://www.nexusmods.com/baldursgate3/mods/1234",
        "label": "Nouvelle classe.",
        "source": "nexus_summary",
    }
    assert len(data["objets"]) == 1
    assert data["sous_classes"] == []
    assert data["dons"] == []


def test_documentation_index_to_json_liste_tous_les_mods_meme_sans_mention():
    entries = [ModDocumentation(pak_file="ModX.pak", mod_name="Mod X")]
    data = documentation_index_to_json(entries)
    assert data["mods"] == [
        {
            "pak_file": "ModX.pak",
            "mod_name": "Mod X",
            "nexus_mod_id": None,
            "nexus_url": None,
            "version": None,
            "mentions": [],
        }
    ]
    assert data["classes"] == data["sous_classes"] == data["dons"] == data["objets"] == []


def test_save_documentation_index_ecrit_un_json_lisible(tmp_path):
    entries = [ModDocumentation(pak_file="ModX.pak", mod_name="Mod X")]
    data = documentation_index_to_json(entries)
    path = tmp_path / "sous_dossier" / "mods_documentation.json"

    save_documentation_index(data, path)

    assert path.is_file()
    reloaded = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded["mods"][0]["mod_name"] == "Mod X"


# --- 16b : parse_stats_entries (format "stats" texte de Larian) -----------


def test_parse_stats_entries_texte_vide():
    assert parse_stats_entries("") == []


def test_parse_stats_entries_une_entree_avec_type_et_data():
    text = """
new entry "ASI"
type "Feat"
using "Feat_Base"
data "DisplayName" "Amélioration de caractéristique"
data "Description" "Augmente une caractéristique."
"""
    entries = parse_stats_entries(text)
    assert entries == [
        StatsEntry(
            name="ASI",
            type="Feat",
            data={
                "DisplayName": "Amélioration de caractéristique",
                "Description": "Augmente une caractéristique.",
            },
        )
    ]


def test_parse_stats_entries_plusieurs_blocs_consecutifs():
    text = """
new entry "Feat_A"
type "Feat"
data "DisplayName" "Premier don"

new entry "Feat_B"
type "Feat"
data "DisplayName" "Second don"
"""
    entries = parse_stats_entries(text)
    assert [e.name for e in entries] == ["Feat_A", "Feat_B"]
    assert entries[0].data["DisplayName"] == "Premier don"
    assert entries[1].data["DisplayName"] == "Second don"


def test_parse_stats_entries_sans_type_ni_data():
    entries = parse_stats_entries('new entry "Vide"\n')
    assert entries == [StatsEntry(name="Vide", type=None, data={})]


# --- 16b : extract_pak_entities (contenu réel du .pak, .pak SYNTHÉTIQUE) --


def test_extract_pak_entities_pak_sans_fichier_stats(tmp_path):
    """Un .pak exploitable mais sans aucun fichier Stats/Generated/Data/*
    ciblé (ex: mod purement cosmétique) : liste vide, pas une erreur."""
    pak_path = tmp_path / "MonMod.pak"
    pak_path.write_bytes(_build_v18_pak_multi([("Mods/MonMod/meta.lsx", b"<save/>")]))
    assert extract_pak_entities(pak_path) == []


def test_extract_pak_entities_extrait_un_don_depuis_feat_txt(tmp_path):
    feat_txt = b"""
new entry "ASI"
type "Feat"
data "DisplayName" "Amelioration de caracteristique"
"""
    pak_path = tmp_path / "MonMod.pak"
    pak_path.write_bytes(
        _build_v18_pak_multi([("Public/MonMod/Stats/Generated/Data/Feat.txt", feat_txt)])
    )
    entities = extract_pak_entities(pak_path)
    assert entities == [
        PakEntity(
            kind="don",
            name="ASI",
            label="Amelioration de caracteristique",
            source="Public/MonMod/Stats/Generated/Data/Feat.txt",
        )
    ]


def test_extract_pak_entities_extrait_objets_depuis_weapon_et_armor(tmp_path):
    weapon_txt = b'new entry "Epee_Runique"\ntype "Weapon"\ndata "DisplayName" "Epee runique"\n'
    armor_txt = b'new entry "Armure_Runique"\ntype "Armor"\n'
    pak_path = tmp_path / "MonMod.pak"
    pak_path.write_bytes(
        _build_v18_pak_multi(
            [
                ("Public/MonMod/Stats/Generated/Data/Weapon.txt", weapon_txt),
                ("Public/MonMod/Stats/Generated/Data/Armor.txt", armor_txt),
            ]
        )
    )
    entities = extract_pak_entities(pak_path)
    assert {e.name for e in entities} == {"Epee_Runique", "Armure_Runique"}
    assert all(e.kind == "objet" for e in entities)
    # Pas de DisplayName pour "Armure_Runique" -> repli sur le nom Larian.
    armure = next(e for e in entities if e.name == "Armure_Runique")
    assert armure.label == "Armure_Runique"
    epee = next(e for e in entities if e.name == "Epee_Runique")
    assert epee.label == "Epee runique"


def test_extract_pak_entities_plusieurs_entrees_dans_le_meme_fichier(tmp_path):
    feat_txt = b'new entry "Feat_A"\ntype "Feat"\n\nnew entry "Feat_B"\ntype "Feat"\n'
    pak_path = tmp_path / "MonMod.pak"
    pak_path.write_bytes(
        _build_v18_pak_multi([("Public/MonMod/Stats/Generated/Data/Feat.txt", feat_txt)])
    )
    entities = extract_pak_entities(pak_path)
    assert {e.name for e in entities} == {"Feat_A", "Feat_B"}
