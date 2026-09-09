"""Téléchargement de fichiers de mods vers le dossier Mods géré."""

from __future__ import annotations

from collections.abc import Callable
from email.message import Message
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from bg3_mod_tui.archives import is_supported_archive

ProgressCallback = Callable[[int, int | None], None]


class DownloadError(RuntimeError):
    """Échec de téléchargement — message destiné à l'utilisateur."""


def _filename_from_content_disposition(header: str | None) -> str | None:
    """Extrait le nom de fichier de l'en-tête `Content-Disposition` de la
    réponse, s'il est présent (gère le format simple `filename="..."`
    ainsi que l'encodage RFC 5987 `filename*=UTF-8''...` via le module
    standard `email`, plutôt que de réinventer ce parsing)."""
    if not header:
        return None
    msg = Message()
    msg["content-disposition"] = header
    return msg.get_filename()


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = unquote(Path(path).name)
    return name or "mod_download.bin"


def _resolve_filename(url: str, headers: httpx.Headers) -> str:
    """Détermine le nom de fichier à utiliser pour la sauvegarde : en
    priorité l'en-tête `Content-Disposition` de la réponse (le plus
    fiable — l'URL elle-même peut être un simple point de terminaison
    générique, ex: les liens de téléchargement mod.io se terminent
    littéralement par `/download`, sans nom de fichier ni extension),
    sinon le dernier segment de l'URL."""
    return _filename_from_content_disposition(headers.get("content-disposition")) or _filename_from_url(url)


def download_file(
    url: str,
    destination_dir: Path,
    *,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Télécharge `url` dans `destination_dir` en streaming, avec suivi de
    progression optionnel. Retourne le chemin du fichier téléchargé.

    Refuse (`DownloadError`, sans rien écrire sur le disque) tout fichier
    dont le nom résolu n'a pas une extension d'archive reconnue
    (`.zip`/`.rar`/`.7z`, voir `archives.is_supported_archive`) — évite de
    se retrouver avec un fichier sans extension (ex: littéralement nommé
    "download") que le pipeline d'extraction ne détectera jamais ensuite,
    et qui reste alors à traîner sans qu'on sache d'où il vient."""
    destination_dir.mkdir(parents=True, exist_ok=True)

    with httpx.stream("GET", url, timeout=30, follow_redirects=True) as resp:
        resp.raise_for_status()

        filename = _resolve_filename(url, resp.headers)
        target = destination_dir / filename
        if not is_supported_archive(target):
            raise DownloadError(
                f"Téléchargement refusé : nom de fichier sans extension "
                f"d'archive reconnue ('{filename}')."
            )

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
