"""Tests de `bg3_mod_tui.pak_origin` : résolution de l'origine des .pak
"isolés" (glisser-déposé direct dans Mods/, aucune archive connue de ce
TUI) — `find_orphaned_paks` (repérage), `match_orphan_by_name` (étape 1,
heuristique), `match_orphan_by_uuid` (étape 2, fiable, via un faux
`read_pak_identity`/`archive_pak_identities`), et
`parse_manual_origin_link`/`load_manual_origins`/`save_manual_origin`
(étape 3, fallback manuel mémorisé)."""

from __future__ import annotations

import json
from pathlib import Path

import bg3_mod_tui.pak_origin as pak_origin
from bg3_mod_tui.inventory import ArchiveEntry
from bg3_mod_tui.pak_origin import (
    MANUAL_ORIGINS_FILENAME,
    find_orphaned_paks,
    load_manual_origins,
    match_orphan_by_name,
    match_orphan_by_uuid,
    parse_manual_origin_link,
    resolve_archive_path,
    save_manual_origin,
)
from bg3_mod_tui.profiles import profile_data_dir


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


def test_parse_manual_origin_link_reconnait_un_lien_nexus():
    parsed = parse_manual_origin_link("https://www.nexusmods.com/baldursgate3/mods/12345")
    assert parsed == {"source": "nexus", "nexus_mod_id": 12345, "modio_slug": None}


def test_parse_manual_origin_link_reconnait_un_lien_modio():
    parsed = parse_manual_origin_link("https://mod.io/g/baldursgate3/m/mon-super-mod")
    assert parsed == {"source": "modio", "nexus_mod_id": None, "modio_slug": "mon-super-mod"}


def test_parse_manual_origin_link_lien_non_reconnu():
    assert parse_manual_origin_link("https://example.com/pas-un-mod") is None
    assert parse_manual_origin_link("n'importe quoi") is None


def test_save_manual_origin_lien_non_reconnu_n_ecrit_rien(tmp_path):
    profiles_dir = tmp_path / "profiles"
    result = save_manual_origin(profiles_dir, "MonProfil", "Isole.pak", "pas un lien")
    assert result is None
    assert not profiles_dir.exists()


def test_save_puis_load_manual_origin_nexus(tmp_path):
    profiles_dir = tmp_path / "profiles"
    origin = save_manual_origin(
        profiles_dir,
        "MonProfil",
        "Isole.pak",
        "https://www.nexusmods.com/baldursgate3/mods/777",
    )
    assert origin is not None
    assert origin.source == "nexus"
    assert origin.nexus_mod_id == 777

    reloaded = load_manual_origins(profiles_dir, "MonProfil")
    assert "Isole.pak" in reloaded
    assert reloaded["Isole.pak"].nexus_mod_id == 777
    assert reloaded["Isole.pak"].url == "https://www.nexusmods.com/baldursgate3/mods/777"


def test_save_manual_origin_modio_puis_load(tmp_path):
    profiles_dir = tmp_path / "profiles"
    origin = save_manual_origin(
        profiles_dir, "MonProfil", "Isole.pak", "https://mod.io/g/baldursgate3/m/mon-mod"
    )
    assert origin is not None
    assert origin.source == "modio"
    assert origin.modio_slug == "mon-mod"

    reloaded = load_manual_origins(profiles_dir, "MonProfil")
    assert reloaded["Isole.pak"].modio_slug == "mon-mod"


def test_load_manual_origins_dossier_absent_renvoie_vide(tmp_path):
    assert load_manual_origins(tmp_path / "profiles", "MonProfil") == {}


def test_save_manual_origin_conserve_les_entrees_existantes_d_autres_pak(tmp_path):
    profiles_dir = tmp_path / "profiles"
    save_manual_origin(
        profiles_dir, "MonProfil", "Premier.pak", "https://www.nexusmods.com/baldursgate3/mods/1"
    )
    save_manual_origin(
        profiles_dir, "MonProfil", "Second.pak", "https://www.nexusmods.com/baldursgate3/mods/2"
    )
    reloaded = load_manual_origins(profiles_dir, "MonProfil")
    assert set(reloaded) == {"Premier.pak", "Second.pak"}


def test_load_manual_origins_fichier_corrompu_renvoie_vide(tmp_path):
    profiles_dir = tmp_path / "profiles"
    dest_dir = profile_data_dir(profiles_dir, "MonProfil")
    dest_dir.mkdir(parents=True)
    (dest_dir / MANUAL_ORIGINS_FILENAME).write_text("{ceci n'est pas du JSON", encoding="utf-8")

    assert load_manual_origins(profiles_dir, "MonProfil") == {}


def test_load_manual_origins_ignore_une_entree_avec_un_champ_inattendu(tmp_path):
    # Fichier édité à la main (ou par une version antérieure/postérieure de
    # l'outil) avec un champ que `ManualPakOrigin` ne connaît pas pour cette
    # entrée : elle est ignorée plutôt que de faire échouer le chargement
    # des autres entrées valides du même fichier.
    profiles_dir = tmp_path / "profiles"
    dest_dir = profile_data_dir(profiles_dir, "MonProfil")
    dest_dir.mkdir(parents=True)
    (dest_dir / MANUAL_ORIGINS_FILENAME).write_text(
        json.dumps(
            {
                "Corrompu.pak": {
                    "url": "https://www.nexusmods.com/baldursgate3/mods/9",
                    "source": "nexus",
                    "nexus_mod_id": 9,
                    "modio_slug": None,
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                    "champ_inconnu": "casse le TypeError attendu",
                },
                "Valide.pak": {
                    "url": "https://www.nexusmods.com/baldursgate3/mods/10",
                    "source": "nexus",
                    "nexus_mod_id": 10,
                    "modio_slug": None,
                    "recorded_at": "2026-01-01T00:00:00+00:00",
                },
            }
        ),
        encoding="utf-8",
    )

    reloaded = load_manual_origins(profiles_dir, "MonProfil")
    assert set(reloaded) == {"Valide.pak"}
    assert reloaded["Valide.pak"].nexus_mod_id == 10
