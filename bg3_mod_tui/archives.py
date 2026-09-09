"""Extraction d'archives de mods (.zip, .rar, .7z).

Le .zip est extrait via le module standard `zipfile`. Le .rar et le .7z
sont extraits en sous-traitant la tâche aux binaires système `unrar` /
`7z` (souvent déjà présents sur les postes de modding BG3, notamment via
les outils tiers du projet) plutôt qu'en ajoutant des dépendances Python
supplémentaires pour ces formats propriétaires.
"""

from __future__ import annotations

import atexit
import shutil
import subprocess
import threading
import zipfile
from pathlib import Path


class ArchiveError(RuntimeError):
    """Échec d'extraction — message destiné à l'utilisateur."""


# Contrairement aux outils lancés via `launcher.py` (délibérément détachés
# pour survivre à la fermeture du TUI), les processus `unrar`/`7z` lancés
# ici sont un détail d'implémentation de l'extraction : on les garde en
# mémoire pour pouvoir les terminer si le TUI se ferme (ou reçoit un signal
# d'interruption) pendant qu'une extraction est en cours, plutôt que de les
# laisser tourner en arrière-plan.
_active_processes: set[subprocess.Popen] = set()
_active_processes_lock = threading.Lock()


def terminate_active_extractions() -> None:
    """Termine les processus d'extraction encore en cours. À appeler à la
    fermeture de l'application ou sur signal d'interruption."""
    with _active_processes_lock:
        procs = list(_active_processes)
    for proc in procs:
        if proc.poll() is None:
            proc.terminate()
    for proc in procs:
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


atexit.register(terminate_active_extractions)


def _extract_zip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)


def _extract_via_binary(binary: str, args: list[str], archive: Path) -> None:
    if shutil.which(binary) is None:
        raise ArchiveError(
            f"L'outil '{binary}' est introuvable dans le PATH, impossible "
            f"d'extraire '{archive.name}'."
        )
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    with _active_processes_lock:
        _active_processes.add(proc)
    try:
        stdout, stderr = proc.communicate()
    finally:
        with _active_processes_lock:
            _active_processes.discard(proc)
    if proc.returncode != 0:
        raise ArchiveError(
            f"Échec de l'extraction de '{archive.name}' via {binary} : "
            f"{stderr.strip() or stdout.strip()}"
        )


def _extract_rar(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if shutil.which("unrar") is not None:
        _extract_via_binary(
            "unrar", ["unrar", "x", "-y", str(archive), f"{dest}/"], archive
        )
        return
    _extract_via_binary("7z", ["7z", "x", "-y", f"-o{dest}", str(archive)], archive)


def _extract_7z(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    _extract_via_binary("7z", ["7z", "x", "-y", f"-o{dest}", str(archive)], archive)


_EXTRACTORS = {
    ".zip": _extract_zip,
    ".rar": _extract_rar,
    ".7z": _extract_7z,
}


def is_supported_archive(path: Path) -> bool:
    return path.suffix.lower() in _EXTRACTORS


def extract_archive(archive: Path, dest: Path) -> None:
    """Extrait `archive` dans `dest` (créé si besoin). Lève `ArchiveError`
    en cas de format non supporté ou d'échec d'extraction."""
    extractor = _EXTRACTORS.get(archive.suffix.lower())
    if extractor is None:
        raise ArchiveError(f"Format d'archive non supporté : '{archive.suffix}'.")
    dest.mkdir(parents=True, exist_ok=True)
    try:
        extractor(archive, dest)
    except ArchiveError:
        raise
    except Exception as exc:
        raise ArchiveError(f"Échec de l'extraction de '{archive.name}' : {exc}") from exc
