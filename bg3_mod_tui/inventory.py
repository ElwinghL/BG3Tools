"""Inventaire JSON des mods : archives connues (avec ID/version/URL Nexus
reconstruits depuis leur nom de fichier) et .pak déployés dans le dossier
Mods du jeu. Les archives Nexus (téléchargement navigateur/API ou Vortex)
encodent toujours l'ID du mod dans leur nom de fichier, ce qui permet de
reconstruire l'URL sans appel API ni lecture du .pak (qui ne contient
lui-même aucun champ URL/source — seulement Name/Author/UUID/Version64)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ProgressFn = Callable[[str], None]
_NOOP_PROGRESS: ProgressFn = lambda _msg: None

# Fréquence (en nombre de .pak traités) des lignes de progression pendant
# l'association pak<->archive — cette boucle est en O(paks * archives) et
# peut prendre un moment sur un stockage lent, d'où le besoin d'un signe de
# vie régulier plutôt qu'un silence total jusqu'au résultat final.
_PAK_PROGRESS_EVERY = 25

NEXUS_MOD_URL = "https://www.nexusmods.com/baldursgate3/mods/{id}"

# Téléchargement navigateur/API Nexus :
# "<Nom>-<id>-<v1>[-<v2>[-<v3>[-<v4>]]]-<timestamp unix 10 chiffres>[_<timestamp additionnel>].<ext>"
#
# `.+?` non-gourmand : on veut le *premier* "-<id>-...-<timestamp>." valide
# en partant de la gauche (le nom du mod peut légitimement commencer par des
# chiffres, ex: "0. NPC Redesign...", mais ceux-ci ne sont jamais suivis
# d'un "-" puis d'une suite de segments numériques se terminant par un
# timestamp à 10 chiffres, donc pas de faux positif sur ces cas).
#
# Le suffixe optionnel "_<chiffres>" gère les noms où un second timestamp a
# été accolé au premier par un second téléchargement fusionné dans le nom
# (ex: "...-1470-2-1693088439_1788973803.zip") — seul le premier timestamp
# (10 chiffres, juste après la version) sert de séparateur, le reste est
# ignoré pour l'extraction de l'ID/version.
_PATTERN_BROWSER = re.compile(
    r"^(?P<name>.+?)-(?P<id>\d+)-(?P<version>\d+(?:-\d+){0,3})-(?P<timestamp>\d{10})"
    r"(?:_\d+)?\.(?P<ext>zip|rar|7z)$",
    re.IGNORECASE,
)

# Téléchargement via Vortex :
# "<Nom> <id> <version> <date ISO>T<heure>Z <hash>.<ext>"
_PATTERN_VORTEX = re.compile(
    r"^(?P<name>.+) (?P<id>\d+) (?P<version>[\d.]+) "
    r"\d{4}-\d{2}-\d{2}T[\d-]+Z [A-Za-z0-9]+\.(?P<ext>zip|rar|7z)$",
    re.IGNORECASE,
)


@dataclass
class ArchiveEntry:
    file: str
    status: str  # "disponible" | "installee" | "a_traiter"
    size_bytes: int
    modified: str
    nexus_mod_id: int | None = None
    nexus_url: str | None = None
    version: str | None = None
    mod_name_guess: str | None = None


@dataclass
class PakEntry:
    file: str
    size_bytes: int
    modified: str
    matched_archive: str | None = None


_DUPLICATE_SUFFIX_RE = re.compile(r" \(\d+\)(\.[A-Za-z0-9]+)$")


def parse_archive_metadata(filename: str) -> dict | None:
    """Extrait (nom, id Nexus, version) du nom d'une archive, si celui-ci
    suit une des deux conventions de téléchargement Nexus connues. Retourne
    None si aucune ne correspond (ex: archive téléchargée depuis GitHub)."""
    # Suffixe de doublon ajouté par le navigateur ("... (1).zip") lors d'un
    # second téléchargement du même fichier : on l'ignore pour la détection.
    filename = _DUPLICATE_SUFFIX_RE.sub(r"\1", filename)
    for pattern in (_PATTERN_BROWSER, _PATTERN_VORTEX):
        match = pattern.match(filename)
        if match:
            return {
                "name": match.group("name").strip(),
                "id": int(match.group("id")),
                "version": match.group("version").replace("-", "."),
            }
    return None


def known_mod_ids(*directories: Path) -> set[int]:
    """Retourne l'ensemble des ID Nexus déjà présents (sous quelque forme
    que ce soit : à traiter, installé, ou encore brut) parmi les archives
    de `directories` — pour savoir quels mods sont déjà téléchargés sans se
    limiter au seul dossier de dépôt initial (une archive déjà extraite a
    été déplacée dans `_installees/`, par exemple)."""
    ids: set[int] = set()
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in (".zip", ".rar", ".7z"):
                continue
            meta = parse_archive_metadata(path.name)
            if meta:
                ids.add(meta["id"])
    return ids


def _mtime_iso(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _scan_archives(directory: Path, status: str) -> list[ArchiveEntry]:
    if not directory.is_dir():
        return []
    entries = []
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in (".zip", ".rar", ".7z"):
            continue
        meta = parse_archive_metadata(path.name)
        entries.append(
            ArchiveEntry(
                file=path.name,
                status=status,
                size_bytes=path.stat().st_size,
                modified=_mtime_iso(path),
                nexus_mod_id=meta["id"] if meta else None,
                nexus_url=NEXUS_MOD_URL.format(id=meta["id"]) if meta else None,
                version=meta["version"] if meta else None,
                mod_name_guess=meta["name"] if meta else None,
            )
        )
    return entries


def _match_pak_to_archive(pak_stem: str, archives: list[ArchiveEntry]) -> str | None:
    """Association au mieux (nom normalisé) entre un .pak et une archive —
    heuristique, non garantie (les noms de .pak et d'archive ne suivent
    aucune convention commune fiable côté BG3/Nexus)."""
    normalized_pak = _normalize(pak_stem)
    if not normalized_pak:
        return None
    best: tuple[str, int] | None = None
    for archive in archives:
        candidate = archive.mod_name_guess or Path(archive.file).stem
        normalized_candidate = _normalize(candidate)
        if not normalized_candidate:
            continue
        if normalized_pak in normalized_candidate or normalized_candidate in normalized_pak:
            score = min(len(normalized_pak), len(normalized_candidate))
            if best is None or score > best[1]:
                best = (archive.file, score)
    return best[0] if best else None


def match_archive_origin(file_stem: str, archives: list[ArchiveEntry]) -> dict | None:
    """Version publique de `_match_pak_to_archive`, retournant directement
    les champs d'origine (ID/URL/version Nexus, nom de l'archive) plutôt
    que juste le nom de l'archive — utilisée pour enrichir les profils
    exportés avec la provenance de chaque mod (best-effort, cf. limite de
    l'heuristique documentée sur `_match_pak_to_archive`)."""
    archive_name = _match_pak_to_archive(file_stem, archives)
    if archive_name is None:
        return None
    archive = next(a for a in archives if a.file == archive_name)
    return {
        "archive": archive.file,
        "nexus_mod_id": archive.nexus_mod_id,
        "nexus_url": archive.nexus_url,
        "version": archive.version,
        "mod_name_guess": archive.mod_name_guess,
    }


def scan_all_archives(
    *,
    archives_dir: Path,
    archives_installed_dir: Path,
    archives_pending_dir: Path,
    on_progress: ProgressFn = _NOOP_PROGRESS,
) -> list[ArchiveEntry]:
    """Recense toutes les archives connues (disponibles, installées, à
    traiter), avec ID/version/URL Nexus reconstruits quand possible —
    utilisé pour retrouver l'origine d'un .pak/DLL déployé (voir
    `match_archive_origin`)."""
    archives: list[ArchiveEntry] = []
    for directory, status, label in (
        (archives_dir, "disponible", "disponibles"),
        (archives_installed_dir, "installee", "installées"),
        (archives_pending_dir, "a_traiter", "à traiter"),
    ):
        on_progress(f"Scan des archives {label} ({directory})...")
        found = _scan_archives(directory, status)
        on_progress(f"  {len(found)} archive(s) {label}.")
        archives.extend(found)
    return archives


def build_inventory(
    *,
    mods_dir: Path,
    archives_dir: Path,
    archives_installed_dir: Path,
    archives_pending_dir: Path,
    on_progress: ProgressFn = _NOOP_PROGRESS,
) -> dict:
    """Construit l'inventaire complet : archives connues (disponibles,
    installées, à traiter) avec ID/version/URL Nexus reconstruits quand
    possible, et .pak actuellement déployés dans le dossier Mods du jeu,
    associés au mieux à leur archive d'origine. `on_progress` (optionnel)
    reçoit des lignes de progression régulières — utile pour distinguer un
    traitement en cours (association pak<->archive en O(paks*archives),
    potentiellement lente sur un stockage lent) d'un blocage."""
    archives = scan_all_archives(
        archives_dir=archives_dir,
        archives_installed_dir=archives_installed_dir,
        archives_pending_dir=archives_pending_dir,
        on_progress=on_progress,
    )

    paks: list[PakEntry] = []
    if mods_dir.is_dir():
        pak_paths = sorted(mods_dir.glob("*.pak"))
        on_progress(f"Association de {len(pak_paths)} .pak à leur archive d'origine...")
        for index, path in enumerate(pak_paths, start=1):
            paks.append(
                PakEntry(
                    file=path.name,
                    size_bytes=path.stat().st_size,
                    modified=_mtime_iso(path),
                    matched_archive=_match_pak_to_archive(path.stem, archives),
                )
            )
            if index % _PAK_PROGRESS_EVERY == 0 or index == len(pak_paths):
                on_progress(f"  {index}/{len(pak_paths)} .pak traités...")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mods_dir": str(mods_dir),
        "counts": {
            "paks": len(paks),
            "archives": len(archives),
            "archives_with_nexus_id": sum(1 for a in archives if a.nexus_mod_id is not None),
        },
        "paks": [asdict(p) for p in paks],
        "archives": [asdict(a) for a in archives],
    }


def find_orphaned_archives(inventory: dict, native_manifest: dict[str, str] | None = None) -> list[dict]:
    """Archives installées (`_installees`, voir `scan_all_archives`) qu'aucun
    .pak actuellement dans `Mods/` (`inventory["paks"][i]["matched_archive"]`,
    voir `_match_pak_to_archive`) ni entrée de `native_mods_manifest.json`
    (`native_manifest`) ne référence — candidates à la suppression pour
    libérer de l'espace, le mod correspondant ayant vraisemblablement été
    désinstallé depuis (.pak supprimé via "Nettoyer les .pak", ou jamais
    extrait avec succès).

    Best-effort, pas une liste garantie sans faux positif : repose sur
    l'association heuristique par nom normalisé de `_match_pak_to_archive`
    (limite documentée sur cette fonction) — à vérifier avant suppression,
    pas à supprimer en masse aveuglément."""
    matched = {p["matched_archive"] for p in inventory["paks"] if p.get("matched_archive")}
    native_archives = set((native_manifest or {}).keys())
    return [
        archive
        for archive in inventory["archives"]
        if archive["status"] == "installee"
        and archive["file"] not in matched
        and archive["file"] not in native_archives
    ]


def save_inventory(inventory: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
