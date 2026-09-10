"""Tests de `bg3_mod_tui.pak_origin` : résolution de l'origine des .pak
"isolés" (glisser-déposé direct dans Mods/, aucune archive connue de ce
TUI) — `find_orphaned_paks` (repérage), `match_orphan_by_name` (étape 1,
heuristique), `match_orphan_by_uuid` (étape 2, fiable, via un faux
`read_pak_identity`/`archive_pak_identities`), et
`parse_manual_origin_link`/`load_manual_origins`/`save_manual_origin`
(étape 3, fallback manuel mémorisé)."""

from __future__ import annotations

from pathlib import Path

import bg3_mod_tui.pak_origin as pak_origin
from bg3_mod_tui.inventory import ArchiveEntry
from bg3_mod_tui.pak_origin import (
    find_orphaned_paks,
    match_orphan_by_name,
    match_orphan_by_uuid,
    resolve_archive_path,
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


def _dirs(tmp_path: Path) -> dict[str, Path]:
    dirs = {
        "archives_dir": tmp_path / "a_traiter_racine",
        "archives_installed_dir": tmp_path / "_installees",
        "archives_pending_dir": tmp_path / "_a_traiter",
    }
    for d in dirs.values():
        d.mkdir()
    return dirs


def test_resolve_archive_path_choisit_le_bon_dossier_selon_le_statut(tmp_path):
    dirs = _dirs(tmp_path)
    archive = _archive("Mod.zip", status="installee")
    assert resolve_archive_path(archive, **dirs) == dirs["archives_installed_dir"] / "Mod.zip"


def test_match_orphan_by_uuid_trouve_l_archive_au_meme_uuid(tmp_path, monkeypatch):
    dirs = _dirs(tmp_path)
    archive = _archive(
        "ArchiveConnue-42-1-0-1690000000.zip",
        status="a_traiter",
        mod_name_guess="ArchiveConnue",
        nexus_mod_id=42,
    )
    (dirs["archives_pending_dir"] / archive.file).write_bytes(b"contenu factice")
    pak_path = tmp_path / "Isole.pak"
    pak_path.write_bytes(b"contenu factice")

    monkeypatch.setattr(
        pak_origin, "read_pak_identity", lambda *a, **k: ("uuid-1234", "Isolé")
    )
    monkeypatch.setattr(
        pak_origin,
        "archive_pak_identities",
        lambda *a, **k: [("uuid-1234", "ArchiveConnue")],
    )

    result = match_orphan_by_uuid(
        pak_path, [archive], divine_exe=Path("Divine.exe"), reference_path=tmp_path, **dirs
    )
    assert result is not None
    assert result["archive"] == archive.file
    assert result["pak_uuid"] == "uuid-1234"


def test_match_orphan_by_uuid_aucune_archive_ne_partage_l_uuid(tmp_path, monkeypatch):
    dirs = _dirs(tmp_path)
    archive = _archive("Autre.zip", status="disponible")
    (dirs["archives_dir"] / archive.file).write_bytes(b"contenu factice")
    pak_path = tmp_path / "Isole.pak"
    pak_path.write_bytes(b"contenu factice")

    monkeypatch.setattr(pak_origin, "read_pak_identity", lambda *a, **k: ("uuid-1234", "Isolé"))
    monkeypatch.setattr(pak_origin, "archive_pak_identities", lambda *a, **k: [("uuid-autre", "Autre")])

    result = match_orphan_by_uuid(
        pak_path, [archive], divine_exe=Path("Divine.exe"), reference_path=tmp_path, **dirs
    )
    assert result is None


def test_match_orphan_by_uuid_pak_sans_meta_lsx_exploitable(tmp_path, monkeypatch):
    dirs = _dirs(tmp_path)
    pak_path = tmp_path / "Isole.pak"
    pak_path.write_bytes(b"contenu factice")

    monkeypatch.setattr(pak_origin, "read_pak_identity", lambda *a, **k: None)

    result = match_orphan_by_uuid(
        pak_path, [], divine_exe=Path("Divine.exe"), reference_path=tmp_path, **dirs
    )
    assert result is None
