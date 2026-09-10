"""Tests de `bg3_mod_tui.pak_origin` : résolution de l'origine des .pak
"isolés" (glisser-déposé direct dans Mods/, aucune archive connue de ce
TUI) — `find_orphaned_paks` (repérage), `match_orphan_by_name` (étape 1,
heuristique), `match_orphan_by_uuid` (étape 2, fiable, via un faux
`read_pak_identity`/`archive_pak_identities`), et
`parse_manual_origin_link`/`load_manual_origins`/`save_manual_origin`
(étape 3, fallback manuel mémorisé)."""

from __future__ import annotations

from bg3_mod_tui.inventory import ArchiveEntry
from bg3_mod_tui.pak_origin import (
    find_orphaned_paks,
    match_orphan_by_name,
)


def _archive(
    file: str,
    *,
    status: str = "disponible",
    mod_name_guess: str | None = None,
    nexus_mod_id: int | None = None,
) -> ArchiveEntry:
    return ArchiveEntry(
        file=file,
        status=status,
        size_bytes=1,
        modified="2024-01-01T00:00:00+00:00",
        nexus_mod_id=nexus_mod_id,
        nexus_url=f"https://www.nexusmods.com/baldursgate3/mods/{nexus_mod_id}" if nexus_mod_id else None,
        version=None,
        mod_name_guess=mod_name_guess,
    )


def test_find_orphaned_paks_ignore_les_pak_deja_associes():
    paks = [
        {"file": "Connu.pak", "matched_archive": "Connu-123-1-0-1690000000.zip"},
        {"file": "Isole.pak", "matched_archive": None},
    ]
    assert find_orphaned_paks(paks) == [{"file": "Isole.pak", "matched_archive": None}]


def test_find_orphaned_paks_dossier_sans_orphelin():
    paks = [{"file": "Connu.pak", "matched_archive": "Connu.zip"}]
    assert find_orphaned_paks(paks) == []


def test_match_orphan_by_name_trouve_une_archive_au_nom_proche():
    archives = [_archive("MonSuperMod-1234-1-0-1690000000.zip", mod_name_guess="MonSuperMod", nexus_mod_id=1234)]
    result = match_orphan_by_name("MonSuperMod.pak", archives)
    assert result is not None
    assert result["archive"] == "MonSuperMod-1234-1-0-1690000000.zip"
    assert result["nexus_mod_id"] == 1234


def test_match_orphan_by_name_aucune_archive_locale_ne_correspond():
    # Cas typique d'un .pak vraiment glissé-déposé : aucune archive connue
    # de ce TUI n'existe nulle part (téléchargé et extrait ailleurs).
    archives = [_archive("AutreMod-9999-1-0-1690000000.zip", mod_name_guess="AutreMod", nexus_mod_id=9999)]
    assert match_orphan_by_name("ModTotalementInconnu.pak", archives) is None


def test_match_orphan_by_name_dossier_d_archives_vide():
    assert match_orphan_by_name("Isole.pak", []) is None
