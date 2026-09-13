"""Tests de `nexus_variant_selection.infer_ut_eotb_preselection` — voir ce
module pour le contexte (mods "Mantis'..." publiant des variantes
Simple/UT/EOTB/UT+EOTB mutuellement exclusives, cochées par erreur toutes
ensemble avant ce correctif). Noms de fichiers repris tels quels de
`BG3_Managed/Profiles/SOLO_MAX_NEXUS/nexus_file_choices.json` (mods réels
déjà rencontrés)."""

from __future__ import annotations

from bg3_mod_tui.nexus_variant_selection import infer_ut_eotb_preselection


def test_no_ut_or_eotb_keyword_returns_none() -> None:
    candidates = [
        (69185, "- - X900 Increase --522-3-30-P7-1725649781.zip"),
        (69187, "X2 Increase-522-3-30-P7-1725650115.zip"),
    ]
    assert infer_ut_eotb_preselection(candidates) is None


def test_simple_ut_eotb_trio_preselects_both_ut_and_eotb() -> None:
    candidates = [
        (84225, "01 - MANTIS' TIEFLING DUO-14055-1-1-0-0-1737173549.zip"),
        (84226, "02 - MANTIS' TIEFLING DUO - UNIQUE TAV-14055-1-1-0-0-1737173621.zip"),
        (84227, "03 - MANTIS' TIEFLING DUO - EOTB-14055-1-1-0-0-1737173667.zip"),
    ]
    assert infer_ut_eotb_preselection(candidates) == {84226, 84227}


def test_combined_ut_eotb_file_is_preselected_alone() -> None:
    candidates = [
        (1, "01 - MANTIS' LE PRINTEMPS COLLECTION-15790-1-0-0-0.zip"),
        (2, "02 - MANTIS' LE PRINTEMPS COLLECTION - UNIQUE TAV-15790.zip"),
        (3, "03 - MANTIS' LE PRINTEMPS COLLECTION - EOTB-15790.zip"),
        (4, "04 - MANTIS' LE PRINTEMPS COLLECTION - EOTB + UT-15790.zip"),
    ]
    assert infer_ut_eotb_preselection(candidates) == {4}


def test_ut_abbreviation_matches_as_whole_word_only() -> None:
    # "UT" ne doit matcher que comme mot entier — pas dans "OUTFIT" ou "TRIBUTE".
    candidates = [
        (1, "Cool Outfit Tribute-1234.zip"),
        (2, "Cool Outfit Tribute EOTB-1234.zip"),
    ]
    assert infer_ut_eotb_preselection(candidates) == {2}


def test_arcane_inspired_collection_ut_abbreviation() -> None:
    candidates = [
        (89249, "01 - MANTIS' ARCANE INSPIRED COLLECTION-14698-1-2-0-0-1744829478.zip"),
        (89250, "02 - MANTIS' ARCANE INSPIRED COLLECTION - UT-14698-1-2-0-0-1744829727.zip"),
        (89251, "03 - MANTIS' ARCANE INSPIRED COLLECTION - EOTB-14698-1-2-0-0-1744829826.zip"),
    ]
    assert infer_ut_eotb_preselection(candidates) == {89250, 89251}
