"""Pipeline d'installation de mods : téléchargement Nexus, nettoyage des
.pak existants, synchronisation de modsettings.lsx, extraction des
archives téléchargées vers le dossier Mods géré.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from bg3_mod_tui.archives import ArchiveError, extract_archive, is_supported_archive
from bg3_mod_tui.downloader import _filename_from_url, download_file
from bg3_mod_tui.log_format import (
    STATUS_ECHEC,
    STATUS_EXAMEN,
    STATUS_IGNORE,
    STATUS_SUCCES,
    fmt_row,
)
from bg3_mod_tui.providers.modio import ModIOAPIError, ModIOClient
from bg3_mod_tui.providers.nexus import (
    NexusAPIError,
    NexusClient,
    parse_mod_links_file,
    remove_mod_links,
)

LogFn = Callable[[str], None]

_INTERNAL_DIR_NAMES = {"_a_traiter", "_installees"}


def _unique_destination(dest_dir: Path, name: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def download_mods_from_links_file(
    client: NexusClient,
    links_file: Path,
    dest_dir: Path,
    *,
    log: LogFn = lambda _msg: None,
) -> dict[str, list]:
    """Télécharge, pour chaque mod listé dans `links_file`, la dernière
    version de chacune de ses variantes ('MAIN'/'UPDATE'/'OPTIONAL', une
    par nom de fichier distinct) vers `dest_dir`. Nécessite un compte
    Nexus Premium pour le téléchargement direct via l'API.

    Retourne {"downloaded": [...], "skipped": [...], "failed": [(id, err)]}.
    """
    mod_ids = parse_mod_links_file(links_file)
    log(f"{len(mod_ids)} mod(s) listé(s) dans {links_file.name}.")

    dest_dir.mkdir(parents=True, exist_ok=True)
    existing_names = " ".join(p.name for p in dest_dir.iterdir() if p.is_file())

    report: dict[str, list] = {"downloaded": [], "skipped": [], "failed": []}

    for mod_id in mod_ids:
        try:
            info = client.mod_info(mod_id)
            label = f"{mod_id} {info.name}"
            version = info.version
        except NexusAPIError:
            label = str(mod_id)
            version = ""

        if re.search(rf"-{mod_id}-\d", existing_names):
            log(fmt_row(label, STATUS_IGNORE, version=version, detail="déjà présent"))
            report["skipped"].append(mod_id)
            continue
        try:
            files = client.latest_files(mod_id)
            for file_id, _file_name in files:
                url = client.download_link(mod_id, file_id)
                path = download_file(url, dest_dir)
                log(fmt_row(label, STATUS_SUCCES, version=version, detail=path.name))
            report["downloaded"].append(mod_id)
        except NexusAPIError as exc:
            log(fmt_row(label, STATUS_ECHEC, version=version, detail=str(exc)))
            report["failed"].append((mod_id, str(exc)))
        except Exception as exc:
            log(fmt_row(label, STATUS_ECHEC, version=version, detail=str(exc)))
            report["failed"].append((mod_id, str(exc)))

    done_ids = set(report["downloaded"]) | set(report["skipped"])
    if done_ids:
        remove_mod_links(links_file, done_ids)
        log(f"{len(done_ids)} lien(s) retiré(s) de {links_file.name}.")

    return report


def download_subscribed_modio_mods(
    client: ModIOClient,
    dest_dir: Path,
    *,
    log: LogFn = lambda _msg: None,
) -> dict[str, list]:
    """Télécharge, pour chaque mod auquel le compte mod.io est abonné, son
    fichier vers `dest_dir`.

    Retourne {"downloaded": [...], "skipped": [...], "failed": [(name, err)]}.
    """
    report: dict[str, list] = {"downloaded": [], "skipped": [], "failed": []}

    try:
        mods = client.subscribed_mods()
    except ModIOAPIError as exc:
        log(f"Erreur : {exc}")
        report["failed"].append(("*", str(exc)))
        return report

    log(f"{len(mods)} mod(s) abonné(s) sur mod.io.")
    dest_dir.mkdir(parents=True, exist_ok=True)

    for mod in mods:
        if not mod.download_url:
            log(fmt_row(mod.name, STATUS_ECHEC, detail="pas de fichier disponible"))
            report["failed"].append((mod.name, "pas de fichier disponible"))
            continue

        target_name = _filename_from_url(mod.download_url)
        if (dest_dir / target_name).exists():
            log(fmt_row(mod.name, STATUS_IGNORE, detail="déjà présent"))
            report["skipped"].append(mod.name)
            continue

        try:
            path = download_file(mod.download_url, dest_dir)
            log(fmt_row(mod.name, STATUS_SUCCES, detail=path.name))
            report["downloaded"].append(mod.name)
        except Exception as exc:
            log(fmt_row(mod.name, STATUS_ECHEC, detail=str(exc)))
            report["failed"].append((mod.name, str(exc)))

    return report


def clean_pak_files(mods_dir: Path, *, log: LogFn = lambda _msg: None) -> list[str]:
    """Supprime les fichiers .pak présents directement dans `mods_dir`."""
    if not mods_dir.is_dir():
        log(f"Dossier Mods introuvable : {mods_dir}")
        return []
    removed = []
    for pak in mods_dir.glob("*.pak"):
        pak.unlink()
        removed.append(pak.name)
        log(f"Supprimé : {pak.name}")
    log(f"{len(removed)} fichier(s) .pak supprimé(s).")
    return removed


def extract_archives_to_mods(
    archives_dir: Path,
    mods_dir: Path,
    pending_dir: Path,
    installed_dir: Path,
    *,
    log: LogFn = lambda _msg: None,
) -> dict[str, list]:
    """Extrait chaque archive de `archives_dir` : les .pak trouvés sont
    copiés (à plat) dans `mods_dir`, puis l'archive traitée est déplacée
    dans `installed_dir`. Si aucune .pak n'est trouvée, l'archive est
    déplacée telle quelle dans `pending_dir` pour examen manuel.

    Retourne {"installed": [...], "pending": [...], "failed": [(name, err)]}.
    """
    mods_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, list] = {"installed": [], "pending": [], "failed": []}

    if not archives_dir.is_dir():
        log(f"Dossier d'archives introuvable : {archives_dir}")
        return report

    archives = [
        p
        for p in archives_dir.iterdir()
        if p.is_file() and is_supported_archive(p)
    ]
    log(f"{len(archives)} archive(s) à traiter dans {archives_dir.name}.")

    for archive in archives:
        with tempfile.TemporaryDirectory(prefix="bg3modtools_") as tmp:
            tmp_path = Path(tmp)
            try:
                extract_archive(archive, tmp_path)
            except ArchiveError as exc:
                log(fmt_row(archive.name, STATUS_ECHEC, detail=str(exc)))
                dest = _unique_destination(pending_dir, archive.name)
                shutil.move(str(archive), str(dest))
                report["failed"].append((archive.name, str(exc)))
                continue

            paks = list(tmp_path.rglob("*.pak"))
            if not paks:
                log(fmt_row(archive.name, STATUS_EXAMEN, detail="aucun .pak trouvé"))
                dest = _unique_destination(pending_dir, archive.name)
                shutil.move(str(archive), str(dest))
                report["pending"].append(archive.name)
                continue

            for pak in paks:
                shutil.copy2(pak, _unique_destination(mods_dir, pak.name))
            log(fmt_row(archive.name, STATUS_SUCCES, detail=f"{len(paks)} .pak installé(s)"))

            dest = _unique_destination(installed_dir, archive.name)
            shutil.move(str(archive), str(dest))
            report["installed"].append(archive.name)

    return report
