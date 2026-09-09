"""Téléchargement de fichiers de mods vers le dossier Mods géré."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

ProgressCallback = Callable[[int, int | None], None]


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = unquote(Path(path).name)
    return name or "mod_download.bin"


def download_file(
    url: str,
    destination_dir: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Télécharge `url` dans `destination_dir` en streaming, avec suivi de
    progression optionnel. Retourne le chemin du fichier téléchargé."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / _filename_from_url(url)

    with httpx.stream("GET", url, timeout=30, follow_redirects=True) as resp:
        resp.raise_for_status()
        total = resp.headers.get("Content-Length")
        total_bytes = int(total) if total is not None else None
        downloaded = 0
        with target.open("wb") as fh:
            for chunk in resp.iter_bytes(chunk_size=65536):
                fh.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total_bytes)

    return target
