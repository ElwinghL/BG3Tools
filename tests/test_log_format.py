"""Tests de `bg3_mod_tui.log_format` : `_pad` (alignement en largeur
d'affichage réelle via `rich.cells.cell_len`, après normalisation NFC —
les caractères larges CJK/emoji comptent pour 2 colonnes, et un accent
décomposé en NFD (lettre + diacritique combinant) est recomposé avant
mesure pour occuper une seule colonne comme sa forme précomposée NFC) et
`fmt_row` (colonnes alignées + échappement du balisage Rich, qui ne
s'applique qu'aux crochets dont le contenu ressemble à un tag Rich valide
— voir `rich.markup.escape`)."""

from __future__ import annotations

import unicodedata

from rich.cells import cell_len

from bg3_mod_tui.log_format import (
    NAME_WIDTH,
    STATUS_SUCCES,
    STATUS_WIDTH,
    VERSION_WIDTH,
    _pad,
    fmt_row,
)


def test_pad_ascii_court_est_complete_a_droite():
    assert _pad("abc", 10) == "abc" + " " * 7


def test_pad_ascii_pile_a_la_largeur():
    assert _pad("abcdefghij", 10) == "abcdefghij"


def test_pad_texte_trop_long_est_tronque_avec_points_de_suspension():
    result = _pad("abcdefghij", 5)
    assert result == "abcd…"
    assert cell_len(result) == 5


def test_pad_largeur_nulle_ne_leve_pas():
    # max(width - 1, 0) protège contre une largeur de 0 (troncature à "").
    result = _pad("abc", 0)
    assert result == "…"


def test_pad_caracteres_larges_cjk_compte_en_largeur_affichage():
    # Chaque caractère CJK occupe 2 cellules d'affichage : "あいう" pèse 6
    # cellules, pas 3 caractères — `_pad` doit tronquer/compléter selon
    # `cell_len`, pas `len()`, sous peine de casser l'alignement des
    # colonnes suivantes dans le RichLog.
    text = "あいう"
    assert len(text) == 3
    assert cell_len(text) == 6

    result = _pad(text, 10)
    assert cell_len(result) == 10
    assert result.startswith(text)

    truncated = _pad(text, 5)
    assert cell_len(truncated) == 5
    assert truncated.endswith("…")


def test_pad_emoji_compte_en_largeur_affichage():
    text = "🎮 mod"
    result = _pad(text, 12)
    assert cell_len(result) == 12


def test_pad_accents_decomposes_nfd_sont_recomposes_et_comptent_une_cellule():
    # "é" décomposé NFD (e + accent combinant U+0301, 2 codepoints) occupe
    # toujours une seule cellule d'affichage une fois recomposé en NFC —
    # `_pad` normalise d'abord en NFC, donc la forme décomposée et sa forme
    # précomposée équivalente ("é" seul) produisent le même padding.
    decomposed = unicodedata.normalize("NFD", "étoile")
    assert len(decomposed) == 7  # "e" + accent combinant + "toile" (5) = 7
    assert cell_len(decomposed) == 6

    result = _pad(decomposed, 10)
    assert cell_len(result) == 10
    assert result == _pad("étoile", 10)  # forme NFC équivalente : même résultat


def test_fmt_row_colonnes_alignees_sur_les_largeurs_par_defaut():
    row = fmt_row("MonMod", STATUS_SUCCES, version="1.2.3", detail="ok")
    padded_name = _pad("MonMod", NAME_WIDTH)
    padded_version = _pad("1.2.3", VERSION_WIDTH)
    # Nom et version occupent exactement leur largeur de colonne (pas de
    # caractères spéciaux ici, donc `escape()` ne change rien à la longueur).
    assert row[:NAME_WIDTH] == padded_name
    assert row[NAME_WIDTH] == " "
    version_start = NAME_WIDTH + 1
    assert row[version_start : version_start + VERSION_WIDTH] == padded_version
    assert STATUS_SUCCES in row
    assert row.endswith("ok")


def test_fmt_row_echappe_les_crochets_style_tag_dans_name_version_detail():
    # `rich.markup.escape` n'échappe que les "[" suivis d'un contenu qui
    # ressemble à un tag valide (lettre minuscule/#/@ en première position)
    # — un nom de mod entre crochets commençant par une majuscule (ex:
    # "[Aza] NPC Redesign", cas réel documenté dans le docstring de
    # `fmt_row`) n'est donc PAS échappé, contrairement à un texte qui
    # ressemble à un vrai tag Rich comme "[red]...[/red]".
    row = fmt_row(
        "[red]Dangereux[/red] Mod",
        STATUS_SUCCES,
        version="[b]1.0[/b]",  # tient dans VERSION_WIDTH (10) sans troncature
        detail="[error] échec",
    )
    assert "\\[red]Dangereux\\[/red]" in row
    assert "\\[b]1.0\\[/b]" in row
    assert "\\[error] échec" in row


def test_fmt_row_crochets_non_tag_ne_sont_pas_echappes():
    # Cas réel cité dans le docstring de `fmt_row` : "[Aza]" ne ressemble
    # pas à un tag Rich (majuscule après le crochet) et n'est donc pas
    # échappé par `rich.markup.escape` — mais reste inoffensif car Rich
    # n'a pas non plus de tag "Aza" à interpréter.
    row = fmt_row("[Aza] NPC Redesign", STATUS_SUCCES)
    assert "[Aza] NPC Redesign" in row


def test_fmt_row_sans_detail_omet_la_colonne():
    row = fmt_row("Mod", STATUS_SUCCES)
    # Pas de section détail ajoutée quand `detail` est vide : la ligne se
    # termine par la balise de fermeture de couleur du statut.
    assert row.rstrip().endswith("]")
    assert row.count("[/") == 1
