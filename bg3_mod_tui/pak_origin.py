"""Résolution de l'origine (Nexus/mod.io) des .pak "isolés" : des .pak
glissés-déposés directement dans Mods/ (ou par un autre mod manager) sans
passer par aucune archive connue de ce TUI — `inventory.PakEntry.
matched_archive` (et donc `inventory.build_inventory()["paks"][i]
["matched_archive"]`) reste alors vide pour eux, faute d'archive de
`archives_dir`/`_installees`/`_a_traiter` partageant leur nom.

Trois mécanismes de résolution, tentés dans cet ordre (fiabilité
croissante) — voir `screens/actions.py` pour leur enchaînement :
1. `match_orphan_by_name` — heuristique par nom, la moins fiable.
2. `match_orphan_by_uuid` — certaine, via l'UUID réel du `meta.lsx` (voir
   `pak_metadata`) plutôt qu'un hash de fichier brut, qui varierait selon
   la compression/le repackaging d'une archive alors que le mod est
   identique — contrairement à l'UUID du `ModuleInfo`, que BG3 lui-même
   utilise pour identifier un mod.
3. Si les deux précédents échouent : demande à l'utilisateur d'indiquer un
   lien Nexus/mod.io (`parse_manual_origin_link`), mémorisé ensuite pour
   ne plus être redemandé aux scans suivants (`load_manual_origins`/
   `save_manual_origin`)."""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from bg3_mod_tui.inventory import ArchiveEntry, match_archive_origin
from bg3_mod_tui.pak_metadata import (
    PakMetadataError,
    archive_pak_identities,
    read_pak_identity,
)
from bg3_mod_tui.profiles import profile_data_dir

LogFn = Callable[[str], None]
_NOOP_LOG: LogFn = lambda _msg: None

MANUAL_ORIGINS_FILENAME = "origines_manuelles_pak.json"


def find_orphaned_paks(paks: list[dict]) -> list[dict]:
    """.pak de `inventory.build_inventory()["paks"]` (liste de dicts, voir
    `inventory.PakEntry`) sans archive associée (`matched_archive` vide) —
    candidats à une résolution d'origine par ce module (glisser-déposer
    direct dans Mods/, hors circuit Nexus/mod.io de ce TUI)."""
    return [p for p in paks if not p.get("matched_archive")]


def match_orphan_by_name(pak_file: str, archives: list[ArchiveEntry]) -> dict | None:
    """Étape 1 (heuristique, la moins fiable) : tente de relier `pak_file`
    (nom de fichier complet d'un .pak isolé) à l'une des archives locales
    déjà connues (`archives_dir`/`_installees`/`_a_traiter`, voir
    `inventory.scan_all_archives`) par similarité de nom — réutilise
    `inventory.match_archive_origin` (même logique que l'association déjà
    faite par `build_inventory`, ici appliquée explicitement à un .pak
    isolé en particulier).

    Ne prouve rien : deux mods différents peuvent avoir un nom proche, et
    un .pak véritablement téléchargé hors de ce TUI (aucune archive locale
    du tout) ne trouvera jamais de correspondance ici — dans ce cas,
    tenter `match_orphan_by_uuid` (fiable), puis en dernier recours la
    saisie manuelle (`parse_manual_origin_link`)."""
    stem = Path(pak_file).stem
    return match_archive_origin(stem, archives)


def resolve_archive_path(
    archive: ArchiveEntry,
    *,
    archives_dir: Path,
    archives_installed_dir: Path,
    archives_pending_dir: Path,
) -> Path:
    """Chemin réel de `archive` sur le disque selon son statut (voir
    `inventory.scan_all_archives` : une même archive se trouve dans l'un
    des trois dossiers selon qu'elle est disponible, installée, ou encore
    à traiter)."""
    roots = {
        "disponible": archives_dir,
        "installee": archives_installed_dir,
        "a_traiter": archives_pending_dir,
    }
    return roots[archive.status] / archive.file


def match_orphan_by_uuid(
    pak_path: Path,
    archives: list[ArchiveEntry],
    *,
    archives_dir: Path,
    archives_installed_dir: Path,
    archives_pending_dir: Path,
    divine_exe: Path,
    reference_path: Path,
    log: LogFn = _NOOP_LOG,
) -> dict | None:
    """Étape 2 (fiable) : lit l'UUID réel du `meta.lsx` de `pak_path` (voir
    `pak_metadata.read_pak_identity`), puis le compare à l'UUID de chaque
    .pak contenu dans les archives locales connues (`pak_metadata.
    archive_pak_identities`) jusqu'à trouver une correspondance exacte.

    Contrairement à `match_orphan_by_name`, un résultat ici est une
    certitude : l'UUID du nœud `ModuleInfo` est l'identifiant que BG3
    lui-même utilise pour un mod, indépendant de tout nom de fichier —
    préféré ici à un hash SHA-256 du .pak brut, qui varierait selon la
    compression ou un repackaging de l'archive alors que le mod est
    identique. Coûteux (extrait chaque archive candidate via Divine.exe) :
    n'a de sens qu'après l'échec de `match_orphan_by_name`, sur un nombre
    limité de .pak isolés — voir l'appelant dans `screens/actions.py`.

    Retourne None si le .pak isolé n'a pas de `meta.lsx` exploitable, ou si
    aucune archive locale ne contient le même UUID."""
    with tempfile.TemporaryDirectory(prefix="bg3_orphan_uuid_") as tmp:
        work_dir = Path(tmp) / "pak"
        work_dir.mkdir()
        try:
            identity = read_pak_identity(
                pak_path, divine_exe=divine_exe, reference_path=reference_path, work_dir=work_dir
            )
        except PakMetadataError as exc:
            log(f"[#D8C091]{pak_path.name} : {exc}[/#D8C091]")
            return None

    if identity is None:
        return None
    pak_uuid, _pak_name = identity

    for archive in archives:
        archive_path = resolve_archive_path(
            archive,
            archives_dir=archives_dir,
            archives_installed_dir=archives_installed_dir,
            archives_pending_dir=archives_pending_dir,
        )
        if not archive_path.is_file():
            continue
        identities = archive_pak_identities(
            archive_path, divine_exe=divine_exe, reference_path=reference_path, log=log
        )
        if any(uuid == pak_uuid for uuid, _name in identities):
            return {
                "archive": archive.file,
                "nexus_mod_id": archive.nexus_mod_id,
                "nexus_url": archive.nexus_url,
                "version": archive.version,
                "mod_name_guess": archive.mod_name_guess,
                "pak_uuid": pak_uuid,
            }
    return None


# Lien direct vers un mod Nexus (même convention que
# `providers.nexus._MOD_URL_RE`).
_NEXUS_URL_RE = re.compile(r"nexusmods\.com/baldursgate3/mods/(\d+)")

# Lien direct vers un mod mod.io : "https://mod.io/g/baldursgate3/m/<slug>"
# (vérifié en ligne sur mod.io/g/baldursgate3 — les mods y sont bien listés
# sous ce schéma). Contrairement à Nexus, cette URL n'encode aucun ID
# numérique (juste un slug texte) : `providers.modio.ModIOClient` n'expose
# par ailleurs aucune recherche par nom/slug (seulement des lookups par ID
# déjà connu), donc aucun moyen local de retrouver l'ID numérique qu'elle
# utilise à partir de ce lien seul — le slug et l'URL complète sont
# mémorisés tels quels, à défaut de mieux, pour un rapprochement manuel
# ultérieur.
_MODIO_URL_RE = re.compile(r"mod\.io/g/[^/]+/m/([a-z0-9][a-z0-9-]*)", re.IGNORECASE)


@dataclass
class ManualPakOrigin:
    """Origine indiquée manuellement par l'utilisateur pour un .pak isolé
    (étape 3, dernier recours après échec de `match_orphan_by_name` et
    `match_orphan_by_uuid`) — mémorisée pour ne plus être redemandée aux
    scans suivants (voir `load_manual_origins`/`save_manual_origin`)."""

    pak_file: str
    url: str
    source: str  # "nexus" | "modio"
    nexus_mod_id: int | None = None
    modio_slug: str | None = None
    recorded_at: str = ""


def parse_manual_origin_link(url: str) -> dict | None:
    """Reconnaît un lien Nexus ou mod.io pointant vers un mod BG3 et en
    extrait ce qui est exploitable localement (voir `_MODIO_URL_RE` pour la
    limite côté mod.io : pas d'ID numérique dans son URL, juste un slug).
    Retourne None si `url` ne correspond à aucune des deux conventions
    connues (lien mal collé, autre site...)."""
    nexus_match = _NEXUS_URL_RE.search(url)
    if nexus_match:
        return {"source": "nexus", "nexus_mod_id": int(nexus_match.group(1)), "modio_slug": None}
    modio_match = _MODIO_URL_RE.search(url)
    if modio_match:
        return {"source": "modio", "nexus_mod_id": None, "modio_slug": modio_match.group(1)}
    return None


def load_manual_origins(profiles_dir: Path, profile_name: str) -> dict[str, ManualPakOrigin]:
    """Charge, pour le profil `profile_name`, les origines de .pak isolés
    indiquées manuellement lors de scans précédents (pak_file ->
    ManualPakOrigin) — voir `save_manual_origin`. Comme
    `profiles.load_blacklisted_files`, un fichier absent ou corrompu vaut
    simplement "rien de mémorisé" plutôt qu'une erreur."""
    path = profile_data_dir(profiles_dir, profile_name) / MANUAL_ORIGINS_FILENAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    origins: dict[str, ManualPakOrigin] = {}
    for pak_file, entry in raw.items():
        try:
            origins[pak_file] = ManualPakOrigin(pak_file=pak_file, **entry)
        except TypeError:
            # Entrée corrompue/champ inattendu (édition manuelle du JSON) :
            # ignorée plutôt que de faire échouer le chargement de tout le
            # fichier pour les autres .pak.
            continue
    return origins


def save_manual_origin(
    profiles_dir: Path, profile_name: str, pak_file: str, url: str
) -> ManualPakOrigin | None:
    """Enregistre l'origine indiquée manuellement pour `pak_file` (étape 3)
    dans le fichier JSON du profil actif, pour ne plus la redemander aux
    scans suivants (voir `load_manual_origins`). Retourne None (et n'écrit
    rien) si `url` ne correspond à aucun lien Nexus/mod.io reconnu par
    `parse_manual_origin_link`."""
    parsed = parse_manual_origin_link(url)
    if parsed is None:
        return None
    origin = ManualPakOrigin(
        pak_file=pak_file,
        url=url,
        source=parsed["source"],
        nexus_mod_id=parsed["nexus_mod_id"],
        modio_slug=parsed["modio_slug"],
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )
    origins = load_manual_origins(profiles_dir, profile_name)
    origins[pak_file] = origin

    dest_dir = profile_data_dir(profiles_dir, profile_name)
    dest_dir.mkdir(parents=True, exist_ok=True)
    serializable = {
        f: {k: v for k, v in asdict(o).items() if k != "pak_file"} for f, o in origins.items()
    }
    (dest_dir / MANUAL_ORIGINS_FILENAME).write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return origin
