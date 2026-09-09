"""Téléchargement de fichiers de mods vers le dossier Mods géré."""

from __future__ import annotations

from collections.abc import Callable, Iterator
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


# Signatures binaires (nombre magique en tête de fichier) des formats
# d'archive supportés (voir `archives.is_supported_archive`) — utilisées en
# dernier recours (voir `_resolve_filename`) quand ni l'en-tête
# Content-Disposition ni l'URL ne fournissent de nom de fichier exploitable
# (ex: mod.io, dont les liens de téléchargement se terminent littéralement
# par `/download`, sans extension, et dont le CDN n'envoie pas toujours de
# Content-Disposition).
_ARCHIVE_SIGNATURES: list[tuple[bytes, str]] = [
    (b"PK\x03\x04", ".zip"),
    (b"PK\x05\x06", ".zip"),  # zip vide
    (b"PK\x07\x08", ".zip"),  # zip "spanned"
    (b"Rar!\x1a\x07\x01\x00", ".rar"),  # RAR 5.0 (plus long, testé en premier)
    (b"Rar!\x1a\x07\x00", ".rar"),  # RAR 4.x
    (b"7z\xbc\xaf\x27\x1c", ".7z"),
]


def _sniff_archive_extension(data: bytes) -> str | None:
    """Devine l'extension d'archive à partir des premiers octets du corps
    de la réponse (signature de format), voir `_ARCHIVE_SIGNATURES`."""
    for signature, extension in _ARCHIVE_SIGNATURES:
        if data.startswith(signature):
            return extension
    return None


def _resolve_filename(
    url: str, resp: httpx.Response, body: Iterator[bytes]
) -> tuple[str, bytes]:
    """Détermine le nom de fichier à utiliser pour la sauvegarde : en
    priorité l'en-tête `Content-Disposition` de la réponse (le plus
    fiable), sinon le dernier segment de l'URL. Si le nom obtenu n'a
    toujours pas d'extension d'archive reconnue, consomme le premier
    morceau de `body` (le même itérateur que l'appelant utilisera ensuite
    pour écrire le fichier — `Response.iter_bytes()` ne peut être itéré
    qu'une seule fois) pour renifler la signature du format et compléter
    le nom. Retourne `(nom de fichier, octets déjà consommés de `body`,
    à réécrire en tête du fichier si le téléchargement se poursuit)`."""
    name = (
        _filename_from_content_disposition(resp.headers.get("content-disposition"))
        or _filename_from_url(url)
    )
    if is_supported_archive(Path(name)):
        return name, b""

    peeked = next(body, b"")
    sniffed = _sniff_archive_extension(peeked)
    if sniffed:
        name = f"{Path(name).stem or 'mod_download'}{sniffed}"
    return name, peeked


def resolve_remote_filename(url: str) -> str:
    """Résout par avance le nom de fichier réel d'une URL de téléchargement
    (voir `_resolve_filename`) sans télécharger le corps de la réponse
    (au-delà du minimum nécessaire au reniflage de signature) — permet de
    vérifier si un fichier est déjà présent avant de lancer un
    téléchargement complet, pour des URL génériques (ex: `.../download`)
    où le nom réel n'est connu qu'une fois la réponse du serveur reçue."""
    with httpx.stream("GET", url, timeout=15, follow_redirects=True) as resp:
        resp.raise_for_status()
        name, _peeked = _resolve_filename(url, resp, resp.iter_bytes(chunk_size=65536))
        return name


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
    (`.zip`/`.rar`/`.7z`, voir `archives.is_supported_archive`) — que ce
    soit d'après l'URL/Content-Disposition ou, à défaut, la signature du
    contenu (voir `_resolve_filename`) — évite de se retrouver avec un
    fichier sans extension (ex: littéralement nommé "download") que le
    pipeline d'extraction ne détectera jamais ensuite, et qui reste alors
    à traîner sans qu'on sache d'où il vient."""
    destination_dir.mkdir(parents=True, exist_ok=True)

    with httpx.stream("GET", url, timeout=30, follow_redirects=True) as resp:
        resp.raise_for_status()

        body = resp.iter_bytes(chunk_size=65536)
        filename, peeked = _resolve_filename(url, resp, body)
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
            if peeked:
                fh.write(peeked)
                downloaded += len(peeked)
                if on_progress:
                    on_progress(downloaded, total_bytes)
            for chunk in body:
                fh.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total_bytes)

    return target
