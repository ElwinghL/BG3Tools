"""Sauvegarde et restauration de profils de mods : une copie de
modsettings.lsx et un manifeste JSON listant l'intégralité des .pak
déployés dans Mods/, des mods DLL déployés dans bin/NativeMods/, et des
fichiers "loose" reliés (hardlink) depuis DataMods/ vers Data/ du jeu —
chacun avec son origine (ID/URL/version Nexus) quand elle a pu être
retrouvée, pour permettre le partage du profil avec d'autres personnes
(voir `profile_archive.py`).

Limite connue de la restauration locale : le manifeste ne garde que les
*noms* de .pak/DLL (pas leur contenu) — DataMods/ est en revanche une copie
permanente et globale (pas par profil), donc les fichiers "loose" peuvent
toujours être reliés. Restaurer modsettings.lsx + relier les loose files
est donc automatique ; les .pak/DLL manquants (supprimés depuis la
sauvegarde, ex: par "Nettoyer les .pak") sont seulement signalés, pas
retéléchargés automatiquement — ils restent récupérables depuis
Archives_installees/_installees/ ou en relançant l'extraction (option 5),
ou via l'import d'une archive de profil qui les embarque directement."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from bg3_mod_tui.game_deploy import deploy_loose_files
from bg3_mod_tui.inventory import ArchiveEntry, match_archive_origin

LogFn = Callable[[str], None]

MODSETTINGS_FILENAME = "modsettings.lsx"
MANIFEST_FILENAME = "manifest.json"
FILE_CHOICES_FILENAME = "nexus_file_choices.json"
_NO_PROFILE_SLUG = "_sans_profil"

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


class ProfileError(RuntimeError):
    pass


def slugify_profile_name(name: str) -> str:
    """Convertit un nom de profil libre en nom de dossier sûr (alphanumérique,
    '_' et '-' uniquement)."""
    slug = _SLUG_RE.sub("_", name.strip()).strip("_")
    if not slug:
        raise ProfileError(f"Nom de profil invalide : {name!r}")
    return slug


def _profile_choices_dir(profiles_dir: Path, profile_name: str) -> Path:
    """Dossier où stocker les données liées au profil `profile_name` mais
    qui ne font pas partie du manifeste (voir `load_blacklisted_files`) —
    utilise le même slug que `save_profile`, ou un slug dédié quand aucun
    profil n'est actif (`profile_name` vide), pour que ce cas ait lui aussi
    sa propre blacklist plutôt que de retomber sur celle d'un profil précis."""
    slug = slugify_profile_name(profile_name) if profile_name else _NO_PROFILE_SLUG
    return profiles_dir / slug


def load_blacklisted_files(profiles_dir: Path, profile_name: str) -> dict[int, dict[int, str]]:
    """Charge, pour le profil `profile_name`, la blacklist des fichiers
    Nexus non retenus lors d'un choix précédent parmi plusieurs variantes
    d'un même mod (mod_id -> {file_id: file_name} à ne plus proposer au
    téléchargement) — voir `mod_pipeline.download_mods_from_links_file`.
    Le nom de fichier est conservé pour pouvoir l'afficher (ex: écran de
    resélection) sans requête réseau supplémentaire. Liée au profil : deux
    profils peuvent avoir fait des choix différents pour un même mod
    multi-fichiers."""
    path = _profile_choices_dir(profiles_dir, profile_name) / FILE_CHOICES_FILENAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        int(mod_id): {int(file_id): file_name for file_id, file_name in files.items()}
        for mod_id, files in raw.items()
    }


def save_blacklisted_files(
    profiles_dir: Path, profile_name: str, blacklist: dict[int, dict[int, str]]
) -> None:
    dest_dir = _profile_choices_dir(profiles_dir, profile_name)
    dest_dir.mkdir(parents=True, exist_ok=True)
    serializable = {
        str(mod_id): {str(file_id): file_name for file_id, file_name in files.items()}
        for mod_id, files in blacklist.items()
        if files
    }
    (dest_dir / FILE_CHOICES_FILENAME).write_text(
        json.dumps(serializable, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def sync_game_profile(modsettings_path: Path, name: str, source_modsettings: Path) -> Path | None:
    """Crée/actualise `PlayerProfiles/<slug>/modsettings.lsx` dans l'AppData
    du jeu à partir de `source_modsettings`, pour que BG3 Mod Manager, le
    Load Order Optimizer et Para Tool proposent notre profil TUI dans leur
    sélecteur — vérifié (chaînes dans leurs binaires : `DiscoverProfiles`,
    `DiscoverVisibleProfiles`, `GetProfilePath`...) qu'aucun des trois ne
    maintient de base de données de profils propre : ils découvrent tous
    leurs profils en énumérant ce même dossier `PlayerProfiles/`.

    `PlayerProfiles/` est déduit de `modsettings_path`
    (`.../PlayerProfiles/Public/modsettings.lsx` -> `.../PlayerProfiles/`).
    Ne fait rien (retourne None) si cette structure n'est pas reconnue, ou
    si `source_modsettings` est introuvable — ne doit jamais faire échouer
    la sauvegarde/restauration du profil elle-même."""
    player_profiles_root = modsettings_path.parent.parent
    if player_profiles_root.name != "PlayerProfiles" or not source_modsettings.is_file():
        return None

    slug = slugify_profile_name(name)
    game_profile_dir = player_profiles_root / slug
    game_profile_dir.mkdir(parents=True, exist_ok=True)
    target = game_profile_dir / MODSETTINGS_FILENAME
    if not target.is_file() or target.read_bytes() != source_modsettings.read_bytes():
        shutil.copy2(source_modsettings, target)
    return game_profile_dir


def _origin_entries(files: list[str], archives: list[ArchiveEntry]) -> list[dict]:
    return [
        {"file": name, "origin": match_archive_origin(Path(name).stem, archives)}
        for name in files
    ]


def save_profile(
    name: str,
    *,
    profiles_dir: Path,
    modsettings_path: Path,
    mods_dir: Path,
    loose_mods_dir: Path,
    native_mods_dir: Path | None = None,
    archives: list[ArchiveEntry] | None = None,
) -> Path:
    """Sauvegarde le profil `name` sous `profiles_dir/<slug>/` : copie de
    `modsettings_path`, et un manifeste JSON listant les .pak présents dans
    `mods_dir`, les DLL présentes dans `native_mods_dir` (bin/NativeMods/,
    si fourni) et les fichiers gérés sous `loose_mods_dir` (mods "loose
    files" reliés par hardlink dans Data/ du jeu). Chaque .pak/DLL est
    enrichi de son origine (ID/URL/version Nexus) quand `archives` (voir
    `inventory.scan_all_archives`) permet de la retrouver — best-effort,
    laissé à `None` sinon. Écrase un profil existant du même nom (slug).
    Retourne le dossier du profil sauvegardé."""
    if not modsettings_path.is_file():
        raise ProfileError(f"modsettings.lsx introuvable : {modsettings_path}")
    archives = archives or []

    dest_dir = profiles_dir / slugify_profile_name(name)
    dest_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(modsettings_path, dest_dir / MODSETTINGS_FILENAME)
    sync_game_profile(modsettings_path, name, modsettings_path)

    paks = sorted(p.name for p in mods_dir.glob("*.pak")) if mods_dir.is_dir() else []
    native_mods = (
        sorted(p.name for p in native_mods_dir.iterdir() if p.is_file())
        if native_mods_dir is not None and native_mods_dir.is_dir()
        else []
    )
    loose_files = (
        sorted(
            str(p.relative_to(loose_mods_dir).as_posix())
            for p in loose_mods_dir.rglob("*")
            if p.is_file()
        )
        if loose_mods_dir.is_dir()
        else []
    )

    manifest = {
        "name": name,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "paks": _origin_entries(paks, archives),
        "native_mods": _origin_entries(native_mods, archives),
        "loose_files": loose_files,
    }
    (dest_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return dest_dir


def find_profile_dir(profiles_dir: Path, name: str) -> Path:
    """Retrouve le dossier d'un profil à partir de son nom : tente d'abord
    le slug direct (cas normal), sinon parcourt les profils existants à la
    recherche d'un manifeste dont le nom sauvegardé correspond (au cas où
    le nom contiendrait des caractères modifiés par le slug)."""
    direct = profiles_dir / slugify_profile_name(name)
    if (direct / MANIFEST_FILENAME).is_file():
        return direct

    if profiles_dir.is_dir():
        for entry in profiles_dir.iterdir():
            manifest_path = entry / MANIFEST_FILENAME
            if not entry.is_dir() or not manifest_path.is_file():
                continue
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("name") == name:
                return entry

    raise ProfileError(f"Profil introuvable : {name!r}")


def manifest_file_names(entries: list) -> set[str]:
    """Extrait les noms de fichiers d'une liste `paks`/`native_mods` du
    manifeste — supporte l'ancien format (liste de noms) et le nouveau
    (liste de `{"file":..., "origin":...}`), pour rester compatible avec
    les profils déjà sauvegardés avant l'ajout de l'origine."""
    return {entry["file"] if isinstance(entry, dict) else entry for entry in entries}


@dataclass
class RestoreReport:
    profile_dir: Path
    loose_files_linked: int
    paks_missing: list[str]  # dans le manifeste mais absents de Mods/
    paks_extra: list[str]  # dans Mods/ mais absents du manifeste
    native_mods_missing: list[str]  # dans le manifeste mais absents de bin/NativeMods/
    native_mods_extra: list[str]  # dans bin/NativeMods/ mais absents du manifeste


def restore_profile(
    name: str,
    *,
    profiles_dir: Path,
    modsettings_path: Path,
    mods_dir: Path,
    loose_mods_dir: Path,
    game_data_dir: Path,
    native_mods_dir: Path | None = None,
    log: LogFn = lambda _msg: None,
) -> RestoreReport:
    """Restaure le profil `name` : remplace `modsettings_path` par la copie
    sauvegardée, puis relie (hardlink) tous les fichiers "loose" gérés dans
    `game_data_dir` (DataMods/ est une copie permanente et globale, donc
    toujours restaurable telle quelle). Compare ensuite les .pak listés
    dans le manifeste à ceux réellement présents dans `mods_dir` (et les
    DLL à celles de `native_mods_dir`, si fourni) — voir la limite connue
    en tête de module. Lève `ProfileError` si le profil ou son
    modsettings.lsx sont introuvables."""
    profile_dir = find_profile_dir(profiles_dir, name)
    saved_modsettings = profile_dir / MODSETTINGS_FILENAME
    if not saved_modsettings.is_file():
        raise ProfileError(f"modsettings.lsx manquant pour le profil {name!r} : {saved_modsettings}")

    manifest = json.loads((profile_dir / MANIFEST_FILENAME).read_text(encoding="utf-8"))

    modsettings_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(saved_modsettings, modsettings_path)
    sync_game_profile(modsettings_path, name, saved_modsettings)
    log(f"modsettings.lsx restauré depuis le profil « {name} ».")

    linked = deploy_loose_files(loose_mods_dir, game_data_dir, log=log)

    current_paks = {p.name for p in mods_dir.glob("*.pak")} if mods_dir.is_dir() else set()
    expected_paks = manifest_file_names(manifest.get("paks", []))

    current_native_mods = (
        {p.name for p in native_mods_dir.iterdir() if p.is_file()}
        if native_mods_dir is not None and native_mods_dir.is_dir()
        else set()
    )
    expected_native_mods = manifest_file_names(manifest.get("native_mods", []))

    return RestoreReport(
        profile_dir=profile_dir,
        loose_files_linked=linked,
        paks_missing=sorted(expected_paks - current_paks),
        paks_extra=sorted(current_paks - expected_paks),
        native_mods_missing=sorted(expected_native_mods - current_native_mods),
        native_mods_extra=sorted(current_native_mods - expected_native_mods),
    )


def list_profiles(profiles_dir: Path) -> list[str]:
    """Liste les noms (tels que sauvegardés, pas les slugs) des profils
    existants sous `profiles_dir`, triés alphabétiquement."""
    if not profiles_dir.is_dir():
        return []
    names = []
    for entry in profiles_dir.iterdir():
        manifest_path = entry / MANIFEST_FILENAME
        if entry.is_dir() and manifest_path.is_file():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                names.append(data.get("name", entry.name))
            except (OSError, json.JSONDecodeError):
                names.append(entry.name)
    return sorted(names)
