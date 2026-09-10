"""Tests de `bg3_mod_tui.mod_pipeline` : `_unique_destination` (évite
d'écraser un fichier existant en suffixant "(1)", "(2)"...),
`extract_archives_to_mods` sur un cas simple avec de vraies archives .zip
temporaires (dédup des .pak déjà présents dans `mods_dir`), et
`download_subscribed_modio_mods` (ne retélécharge pas un mod mod.io déjà
installé/en attente)."""

from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path

from bg3_mod_tui.inventory import ArchiveEntry
from bg3_mod_tui.mod_pipeline import (
    _unique_destination,
    check_nexus_updates,
    cleanup_duplicate_archives,
    download_subscribed_modio_mods,
    extract_archives_to_mods,
)
from bg3_mod_tui.providers.modio import ModIOMod
from bg3_mod_tui.providers.nexus import NexusAPIError, NexusMod


def _make_zip(path: Path, *entries: tuple[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries:
            zf.writestr(name, content)


def test_unique_destination_nom_disponible_reste_inchange(tmp_path):
    dest = _unique_destination(tmp_path, "mod.zip")
    assert dest == tmp_path / "mod.zip"
    assert not dest.exists()


def test_unique_destination_cree_le_dossier_de_destination(tmp_path):
    dest_dir = tmp_path / "sous_dossier"
    dest = _unique_destination(dest_dir, "mod.zip")
    assert dest_dir.is_dir()
    assert dest == dest_dir / "mod.zip"


def test_unique_destination_nom_deja_pris_suffixe_1(tmp_path):
    (tmp_path / "mod.zip").write_bytes(b"contenu existant")
    dest = _unique_destination(tmp_path, "mod.zip")
    assert dest == tmp_path / "mod (1).zip"


def test_unique_destination_plusieurs_collisions_incrementent_le_suffixe(tmp_path):
    (tmp_path / "mod.zip").write_bytes(b"a")
    (tmp_path / "mod (1).zip").write_bytes(b"b")
    (tmp_path / "mod (2).zip").write_bytes(b"c")
    dest = _unique_destination(tmp_path, "mod.zip")
    assert dest == tmp_path / "mod (3).zip"


def test_unique_destination_preserve_l_extension(tmp_path):
    (tmp_path / "archive.tar.zip").write_bytes(b"a")
    dest = _unique_destination(tmp_path, "archive.tar.zip")
    assert dest.suffix == ".zip"
    assert dest.name == "archive.tar (1).zip"


def _make_pipeline_dirs(tmp_path: Path) -> dict[str, Path]:
    dirs = {
        "archives_dir": tmp_path / "a_traiter",
        "mods_dir": tmp_path / "Mods",
        "pending_dir": tmp_path / "_a_traiter",
        "installed_dir": tmp_path / "_installees",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)
    return dirs


def test_extract_archives_to_mods_installe_un_pak_simple(tmp_path):
    dirs = _make_pipeline_dirs(tmp_path)
    _make_zip(dirs["archives_dir"] / "MonMod.zip", ("MonMod.pak", b"donnees pak"))

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert report["installed"] == ["MonMod.zip"]
    assert report["pending"] == []
    assert report["failed"] == []
    assert (dirs["mods_dir"] / "MonMod.pak").is_file()
    assert (dirs["installed_dir"] / "MonMod.zip").is_file()
    assert not (dirs["archives_dir"] / "MonMod.zip").exists()


def test_extract_archives_to_mods_dedup_pak_deja_present(tmp_path):
    # Le .pak "MonMod.pak" est déjà dans mods_dir (ex: extrait d'un
    # précédent passage) : l'extraction d'une nouvelle archive fournissant
    # un .pak de même nom ne doit PAS l'écraser ni créer un doublon suffixé
    # "MonMod (1).pak" — le .pak est ignoré (contenu existant préservé), et
    # comme il s'agit du seul .pak de l'archive, celle-ci est classée
    # "skipped" plutôt que "installed" (rien de nouveau à en tirer).
    dirs = _make_pipeline_dirs(tmp_path)
    (dirs["mods_dir"] / "MonMod.pak").write_bytes(b"ancienne version")
    _make_zip(dirs["archives_dir"] / "MonMod-update.zip", ("MonMod.pak", b"nouvelle version"))

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert report["installed"] == []
    assert report["skipped"] == ["MonMod-update.zip"]
    assert (dirs["mods_dir"] / "MonMod.pak").read_bytes() == b"ancienne version"
    assert not (dirs["mods_dir"] / "MonMod (1).pak").exists()
    # L'archive est tout de même déplacée vers _installees/ (rien de plus à
    # en tirer dans archives_dir), même si aucun .pak n'a été copié.
    assert (dirs["installed_dir"] / "MonMod-update.zip").is_file()
    assert not (dirs["archives_dir"] / "MonMod-update.zip").exists()


def test_extract_archives_to_mods_pak_partiellement_deja_present(tmp_path):
    # Archive avec deux .pak, dont un seul déjà présent dans mods_dir :
    # l'archive reste "installed" (au moins un .pak neuf copié), et le
    # détail journalisé mentionne le nombre de .pak ignorés en doublon.
    dirs = _make_pipeline_dirs(tmp_path)
    (dirs["mods_dir"] / "Deja.pak").write_bytes(b"deja la")
    _make_zip(
        dirs["archives_dir"] / "Combo.zip",
        ("Deja.pak", b"contenu ignore"),
        ("Nouveau.pak", b"contenu neuf"),
    )
    logs: list[str] = []

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
        log=logs.append,
    )

    assert report["installed"] == ["Combo.zip"]
    assert report["skipped"] == []
    assert (dirs["mods_dir"] / "Deja.pak").read_bytes() == b"deja la"
    assert (dirs["mods_dir"] / "Nouveau.pak").read_bytes() == b"contenu neuf"
    assert any("déjà présent" in line for line in logs)


def test_extract_archives_to_mods_archive_sans_pak_ni_dossier_connu_va_en_examen(tmp_path):
    dirs = _make_pipeline_dirs(tmp_path)
    _make_zip(dirs["archives_dir"] / "Inconnu.zip", ("lisez-moi.txt", b"rien d'utile"))

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert report["pending"] == ["Inconnu.zip"]
    assert report["installed"] == []
    assert (dirs["pending_dir"] / "Inconnu.zip").is_file()


def test_extract_archives_to_mods_archive_corrompue_est_signalee_en_echec(tmp_path):
    dirs = _make_pipeline_dirs(tmp_path)
    bad = dirs["archives_dir"] / "Corrompu.zip"
    bad.write_bytes(b"pas un vrai zip")

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert len(report["failed"]) == 1
    assert report["failed"][0][0] == "Corrompu.zip"
    assert (dirs["pending_dir"] / "Corrompu.zip").is_file()


def _make_zip_bytes(*entries: tuple[str, bytes]) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


def test_extract_archives_to_mods_sans_zip_imbrique_comportement_inchange(tmp_path):
    # Une archive "normale" (pas de ZIP/RAR/7z imbriqué à l'intérieur) est
    # traitée exactement comme avant — aucune mention de ZIP imbriqué dans
    # les logs, et `select_nested_archives` n'est jamais sollicité.
    dirs = _make_pipeline_dirs(tmp_path)
    _make_zip(dirs["archives_dir"] / "MonMod.zip", ("MonMod.pak", b"donnees pak"))
    logs: list[str] = []

    def select_nested_archives(archive_name, candidates):
        raise AssertionError("ne doit pas être appelé sans ZIP imbriqué")

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
        select_nested_archives=select_nested_archives,
        log=logs.append,
    )

    assert report["installed"] == ["MonMod.zip"]
    assert (dirs["mods_dir"] / "MonMod.pak").is_file()
    assert not any("imbriqué" in line for line in logs)


def test_extract_archives_to_mods_zip_imbrique_choisi_est_extrait(tmp_path):
    # L'archive principale ne contient pas de .pak directement, mais un
    # ZIP imbriqué ("Interne.zip") qui, lui, en contient un. Quand
    # `select_nested_archives` choisit de le garder, il est extrait à son
    # tour et son .pak rejoint mods_dir.
    dirs = _make_pipeline_dirs(tmp_path)
    inner_bytes = _make_zip_bytes(("Interne.pak", b"contenu interne"))
    _make_zip(dirs["archives_dir"] / "Conteneur.zip", ("Interne.zip", inner_bytes))
    logs: list[str] = []

    def select_nested_archives(archive_name, candidates):
        assert archive_name == "Conteneur.zip"
        assert [p.name for p in candidates] == ["Interne.zip"]
        return candidates  # tout garder

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
        select_nested_archives=select_nested_archives,
        log=logs.append,
    )

    assert report["installed"] == ["Conteneur.zip"]
    assert (dirs["mods_dir"] / "Interne.pak").read_bytes() == b"contenu interne"
    assert any("retenu" in line for line in logs)


def test_extract_archives_to_mods_zip_imbrique_refuse_est_ignore(tmp_path):
    # Même archive que ci-dessus, mais `select_nested_archives` refuse le
    # ZIP imbriqué : son contenu (.pak compris) n'est jamais extrait, et
    # comme rien d'autre n'est trouvé dans l'archive principale, celle-ci
    # part en examen manuel (`pending_dir`).
    dirs = _make_pipeline_dirs(tmp_path)
    inner_bytes = _make_zip_bytes(("Interne.pak", b"contenu interne"))
    _make_zip(dirs["archives_dir"] / "Conteneur.zip", ("Interne.zip", inner_bytes))
    logs: list[str] = []

    def select_nested_archives(archive_name, candidates):
        return []  # rien garder

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
        select_nested_archives=select_nested_archives,
        log=logs.append,
    )

    assert report["pending"] == ["Conteneur.zip"]
    assert not (dirs["mods_dir"] / "Interne.pak").exists()
    assert any("ignoré" in line for line in logs)


def test_extract_archives_to_mods_zip_imbrique_sans_callback_garde_tout_par_defaut(tmp_path):
    # Sans `select_nested_archives` (contexte non interactif), le
    # comportement par défaut documenté est de tout garder.
    dirs = _make_pipeline_dirs(tmp_path)
    inner_bytes = _make_zip_bytes(("Interne.pak", b"contenu interne"))
    _make_zip(dirs["archives_dir"] / "Conteneur.zip", ("Interne.zip", inner_bytes))

    report = extract_archives_to_mods(
        dirs["archives_dir"],
        dirs["mods_dir"],
        dirs["pending_dir"],
        dirs["installed_dir"],
    )

    assert report["installed"] == ["Conteneur.zip"]
    assert (dirs["mods_dir"] / "Interne.pak").read_bytes() == b"contenu interne"


def _archive_entry(**overrides) -> ArchiveEntry:
    base = dict(
        file="MonMod-42-1-0-1700000000.zip",
        status="disponible",
        size_bytes=100,
        modified="2024-01-01T00:00:00+00:00",
        nexus_mod_id=42,
        nexus_url="https://www.nexusmods.com/baldursgate3/mods/42",
        version="1.0",
        mod_name_guess="MonMod",
    )
    base.update(overrides)
    return ArchiveEntry(**base)


class _FakeNexusClient:
    def __init__(self, mods_by_id: dict[int, NexusMod], *, fail_ids: set[int] | None = None) -> None:
        self._mods_by_id = mods_by_id
        self._fail_ids = fail_ids or set()

    def mod_info(self, mod_id: int) -> NexusMod:
        if mod_id in self._fail_ids:
            raise NexusAPIError(f"Mod Nexus {mod_id} introuvable (404).")
        return self._mods_by_id[mod_id]


def test_check_nexus_updates_detecte_une_version_plus_recente():
    archive = _archive_entry()
    client = _FakeNexusClient({42: NexusMod(mod_id=42, name="MonMod", version="1.1", summary="")})

    report = check_nexus_updates(client, [archive])

    assert report["up_to_date"] == []
    assert report["failed"] == []
    assert len(report["outdated"]) == 1
    entry = report["outdated"][0]
    assert entry["nexus_mod_id"] == 42
    assert entry["local_version"] == "1.0"
    assert entry["remote_version"] == "1.1"


def test_check_nexus_updates_deja_a_jour():
    archive = _archive_entry(version="1.1")
    client = _FakeNexusClient({42: NexusMod(mod_id=42, name="MonMod", version="1.1", summary="")})

    report = check_nexus_updates(client, [archive])

    assert report["outdated"] == []
    assert report["up_to_date"] == [42]


def test_check_nexus_updates_ignore_les_archives_sans_id_nexus():
    archive = _archive_entry(nexus_mod_id=None, version=None)
    client = _FakeNexusClient({})

    report = check_nexus_updates(client, [archive])

    assert report == {"outdated": [], "up_to_date": [], "failed": []}


def test_check_nexus_updates_compare_a_la_meilleure_copie_locale():
    # Deux exemplaires locaux du même mod (ex: un vieux dans _installees,
    # un plus récent dans disponible/) : on compare à la meilleure version
    # locale, pas à la première rencontrée, et un seul appel API est fait.
    old_copy = _archive_entry(file="MonMod-42-1-0-1700000000.zip", version="1.0", status="installee")
    new_copy = _archive_entry(file="MonMod-42-1-2-1700000001.zip", version="1.2", status="disponible")
    calls = []

    class _CountingClient(_FakeNexusClient):
        def mod_info(self, mod_id: int) -> NexusMod:
            calls.append(mod_id)
            return super().mod_info(mod_id)

    client = _CountingClient({42: NexusMod(mod_id=42, name="MonMod", version="1.2", summary="")})

    report = check_nexus_updates(client, [old_copy, new_copy])

    assert calls == [42]
    assert report["outdated"] == []
    assert report["up_to_date"] == [42]


def test_check_nexus_updates_erreur_api_est_reportee_en_echec():
    archive = _archive_entry()
    client = _FakeNexusClient({}, fail_ids={42})

    report = check_nexus_updates(client, [archive])

    assert report["outdated"] == []
    assert report["up_to_date"] == []
    assert len(report["failed"]) == 1
    assert report["failed"][0][0] == 42


class _FakeModIOClient:
    def __init__(self, mods: list[ModIOMod]) -> None:
        self._mods = mods

    def subscribed_mods(self) -> list[ModIOMod]:
        return self._mods


def test_download_subscribed_modio_mods_deja_installe_n_est_pas_retelecharge(tmp_path):
    # Reproduit le bug racine : un mod mod.io déjà déplacé vers
    # `_installees` (installé lors d'un run précédent) ne doit pas être
    # retéléchargé, sous peine de créer une archive dupliquée (suffixée
    # "(1)" par `_unique_destination` lors du prochain passage
    # d'`extract_archives_to_mods`, faute de mieux le nom d'origine étant
    # déjà pris dans `_installees`).
    dest_dir = tmp_path / "a_traiter"
    installed_dir = tmp_path / "_installees"
    installed_dir.mkdir(parents=True)
    (installed_dir / "Aesir's Champion Set-modio5990151.zip").write_bytes(b"contenu deja installe")

    client = _FakeModIOClient(
        [ModIOMod(mod_id=5990151, name="Aesir's Champion Set", summary="", download_url=None)]
    )

    report = download_subscribed_modio_mods(
        client, dest_dir, archives_installed_dir=installed_dir
    )

    assert report["skipped"] == ["Aesir's Champion Set"]
    assert report["downloaded"] == []
    assert report["failed"] == []
    assert not dest_dir.exists() or not any(dest_dir.iterdir())


def test_download_subscribed_modio_mods_detecte_aussi_via_le_dossier_en_attente(tmp_path):
    dest_dir = tmp_path / "a_traiter"
    pending_dir = tmp_path / "_a_traiter"
    pending_dir.mkdir(parents=True)
    (pending_dir / "MonMod-modio42.zip").write_bytes(b"x")

    client = _FakeModIOClient([ModIOMod(mod_id=42, name="MonMod", summary="", download_url=None)])

    report = download_subscribed_modio_mods(
        client, dest_dir, archives_pending_dir=pending_dir
    )

    assert report["skipped"] == ["MonMod"]


def test_download_subscribed_modio_mods_mod_absent_sans_download_url_echoue(tmp_path):
    # Sans les dossiers de détection (ou si le mod n'y figure vraiment
    # pas), le comportement antérieur au correctif est inchangé : un mod
    # sans URL de téléchargement échoue normalement (pas de faux "déjà
    # présent").
    dest_dir = tmp_path / "a_traiter"
    client = _FakeModIOClient([ModIOMod(mod_id=99, name="AutreMod", summary="", download_url=None)])

    report = download_subscribed_modio_mods(client, dest_dir)

    assert report["failed"] == [("AutreMod", "pas de fichier disponible")]
    assert report["skipped"] == []


def _touch_with_mtime(path: Path, content: bytes, mtime: float) -> None:
    path.write_bytes(content)
    os.utime(path, (mtime, mtime))


def test_cleanup_duplicate_archives_dossier_vide_ou_absent(tmp_path):
    assert cleanup_duplicate_archives(tmp_path)["removed"] == []
    assert cleanup_duplicate_archives(tmp_path / "n_existe_pas")["removed"] == []


def test_cleanup_duplicate_archives_supprime_les_doublons_de_contenu_identique(tmp_path):
    # Cas typique observé dans _installees : même mod mod.io retéléchargé
    # à trois reprises (contenu identique, suffixes "(1)", "(2)" ajoutés
    # par _unique_destination faute de mieux).
    now = time.time()
    base = tmp_path / "Aesir's Champion Set-modio5990151.zip"
    dup1 = tmp_path / "Aesir's Champion Set-modio5990151 (1).zip"
    dup2 = tmp_path / "Aesir's Champion Set-modio5990151 (2).zip"
    content_size = len(b"contenu identique")
    _touch_with_mtime(base, b"contenu identique", now - 200)
    _touch_with_mtime(dup1, b"contenu identique", now - 100)
    _touch_with_mtime(dup2, b"contenu identique", now)

    report = cleanup_duplicate_archives(tmp_path)

    assert sorted(report["removed"]) == sorted([dup1.name, dup2.name])
    assert report["conflicts"] == []
    assert report["freed_bytes"] == content_size * 2
    assert base.is_file()  # le plus ancien est conservé
    assert not dup1.exists()
    assert not dup2.exists()


def test_cleanup_duplicate_archives_conserve_le_plus_ancien(tmp_path):
    now = time.time()
    older = tmp_path / "Mod-modio1.zip"
    newer = tmp_path / "Mod-modio1 (1).zip"
    # Écrit dans le désordre pour vérifier que c'est bien mtime qui tranche,
    # pas l'ordre de découverte du dossier.
    _touch_with_mtime(newer, b"x", now)
    _touch_with_mtime(older, b"x", now - 500)

    report = cleanup_duplicate_archives(tmp_path)

    assert older.is_file()
    assert not newer.exists()
    assert report["removed"] == [newer.name]


def test_cleanup_duplicate_archives_ignore_les_memes_noms_de_contenu_different(tmp_path):
    # Même nom de base mais contenu différent (ex: mise à jour du mod
    # retéléchargée sous un nom suffixé) : ne doit PAS être supprimé
    # aveuglément sur la seule foi du nom, seulement rapporté en conflit.
    base = tmp_path / "Mod-modio1.zip"
    other = tmp_path / "Mod-modio1 (1).zip"
    base.write_bytes(b"version A")
    other.write_bytes(b"version B, plus recente")

    report = cleanup_duplicate_archives(tmp_path)

    assert report["removed"] == []
    assert report["conflicts"] == ["Mod-modio1.zip"]
    assert base.is_file()
    assert other.is_file()


def test_cleanup_duplicate_archives_n_affecte_pas_les_fichiers_sans_doublon(tmp_path):
    unique = tmp_path / "UnMod-modio1.zip"
    unique.write_bytes(b"contenu")

    report = cleanup_duplicate_archives(tmp_path)

    assert report["removed"] == []
    assert report["conflicts"] == []
    assert unique.is_file()


def test_cleanup_duplicate_archives_ignore_les_fichiers_non_archives(tmp_path):
    (tmp_path / "notes.txt").write_text("pas une archive")
    (tmp_path / "notes (1).txt").write_text("pas une archive non plus")

    report = cleanup_duplicate_archives(tmp_path)

    assert report["removed"] == []
    assert (tmp_path / "notes.txt").is_file()
    assert (tmp_path / "notes (1).txt").is_file()
