"""Pipeline d'installation de mods : téléchargement Nexus, nettoyage des
.pak existants, synchronisation de modsettings.lsx, extraction des
archives téléchargées vers le dossier Mods géré.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from bg3_mod_tui.archives import ArchiveError, extract_archive, is_supported_archive
from bg3_mod_tui.downloader import download_file, resolve_remote_filename
from bg3_mod_tui.game_deploy import deploy_loose_files
from bg3_mod_tui.inventory import known_mod_ids, known_modio_ids
from bg3_mod_tui.native_mods import (
    NativeModsManifestError,
    deploy_native_mod_archive,
    load_manifest as load_native_mods_manifest,
)
from bg3_mod_tui.log_format import (
    STATUS_ECHEC,
    STATUS_EXAMEN,
    STATUS_IGNORE,
    STATUS_SUCCES,
    fmt_row,
)
from bg3_mod_tui.profiles import load_blacklisted_files, save_blacklisted_files
from bg3_mod_tui.providers.modio import ModIOAPIError, ModIOClient
from bg3_mod_tui.providers.nexus import (
    NexusAPIError,
    NexusClient,
    parse_mod_links_file,
    remove_mod_links,
)

LogFn = Callable[[str], None]
# Reçoit (mod_id, nom du mod, [(file_id, file_name), ...] variantes encore
# candidates) quand un mod a plusieurs fichiers éligibles à choisir parmi
# — doit retourner les file_id à conserver (les autres rejoignent la
# blacklist du profil actif). Une liste vide est un choix valide (le mod
# entier est alors blacklisté).
SelectFilesFn = Callable[[int, str, list[tuple[int, str]]], list[int]]

# Reçoit (nom de l'archive parente, [chemin des ZIP/RAR/7z imbriqués trouvés
# à l'intérieur, ...]) quand une archive extraite contient elle-même
# d'autres archives au lieu de .pak directement — doit retourner les
# chemins à garder (et donc extraire à leur tour) parmi ceux reçus. Une
# liste vide est un choix valide (aucune archive imbriquée n'est gardée).
# Voir `extract_archives_to_mods`.
SelectNestedArchivesFn = Callable[[str, list[Path]], list[Path]]

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
    archives_installed_dir: Path | None = None,
    archives_pending_dir: Path | None = None,
    profiles_dir: Path | None = None,
    profile_name: str = "",
    select_files: SelectFilesFn | None = None,
    log: LogFn = lambda _msg: None,
) -> dict[str, list]:
    """Télécharge, pour chaque mod listé dans `links_file`, ses fichiers
    éligibles ('MAIN'/'UPDATE'/'OPTIONAL', une variante distincte par nom
    de fichier) vers `dest_dir`. Nécessite un compte Nexus Premium pour le
    téléchargement direct via l'API.

    Quand un mod a plusieurs variantes candidates (après exclusion de
    celles déjà blacklistées pour le profil `profile_name`, voir
    `profiles.load_blacklisted_files`), `select_files` est appelé pour
    demander lesquelles garder — les autres rejoignent la blacklist (elles
    ne seront plus proposées tant qu'elles n'auront pas été resélectionnées,
    ex: depuis l'inventaire). Sans `select_files`, toutes les variantes
    candidates sont téléchargées (comportement historique, utile en
    contexte non-interactif). Une seule variante candidate est téléchargée
    directement, sans demander (rien d'ambigu à trancher).

    Un mod est considéré comme déjà présent s'il a une archive dans
    `dest_dir` OU dans `archives_installed_dir`/`archives_pending_dir` (une
    archive déjà extraite a été déplacée hors de `dest_dir`, sans quoi elle
    serait retéléchargée à chaque passage).

    Retourne {"downloaded": [...], "skipped": [...], "failed": [(id, err)]}.
    """
    mod_ids = parse_mod_links_file(links_file)
    log(f"{len(mod_ids)} mod(s) listé(s) dans {links_file.name}.")

    dest_dir.mkdir(parents=True, exist_ok=True)
    already_present_ids = known_mod_ids(
        dest_dir, *(d for d in (archives_installed_dir, archives_pending_dir) if d is not None)
    )

    blacklist = load_blacklisted_files(profiles_dir, profile_name) if profiles_dir is not None else {}
    blacklist_dirty = False

    report: dict[str, list] = {"downloaded": [], "skipped": [], "failed": []}

    total = len(mod_ids)
    for index, mod_id in enumerate(mod_ids, start=1):
        progress = f"[{index}/{total}]"
        try:
            info = client.mod_info(mod_id)
            label = f"{progress} {mod_id} {info.name}"
            version = info.version
        except NexusAPIError:
            label = f"{progress} {mod_id}"
            info = None
            version = ""

        if mod_id in already_present_ids:
            log(fmt_row(label, STATUS_IGNORE, version=version, detail="déjà présent"))
            report["skipped"].append(mod_id)
            continue
        try:
            files = client.latest_files(mod_id)
            excluded_ids = set(blacklist.get(mod_id, {}))
            candidates = [(fid, fname) for fid, fname in files if fid not in excluded_ids]

            if not candidates:
                log(fmt_row(label, STATUS_IGNORE, version=version, detail="toutes les variantes sont blacklistées"))
                report["skipped"].append(mod_id)
                continue

            if len(candidates) > 1 and select_files is not None:
                mod_name = info.name if info is not None else label
                chosen_ids = set(select_files(mod_id, mod_name, candidates))
                rejected = {fid: fname for fid, fname in candidates if fid not in chosen_ids}
                if rejected:
                    blacklist.setdefault(mod_id, {}).update(rejected)
                    blacklist_dirty = True
                to_download = [pair for pair in candidates if pair[0] in chosen_ids]
            else:
                to_download = candidates

            if not to_download:
                log(fmt_row(label, STATUS_IGNORE, version=version, detail="aucune variante retenue"))
                report["skipped"].append(mod_id)
                continue

            for file_id, _file_name in to_download:
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

    if blacklist_dirty and profiles_dir is not None:
        save_blacklisted_files(profiles_dir, profile_name, blacklist)

    done_ids = set(report["downloaded"]) | set(report["skipped"])
    if done_ids:
        remove_mod_links(links_file, done_ids)
        log(f"{len(done_ids)} lien(s) retiré(s) de {links_file.name}.")

    return report


def download_subscribed_modio_mods(
    client: ModIOClient,
    dest_dir: Path,
    *,
    archives_installed_dir: Path | None = None,
    archives_pending_dir: Path | None = None,
    log: LogFn = lambda _msg: None,
) -> dict[str, list]:
    """Télécharge, pour chaque mod auquel le compte mod.io est abonné, son
    fichier vers `dest_dir`.

    Un mod est considéré comme déjà présent s'il a une archive dans
    `dest_dir` OU dans `archives_installed_dir`/`archives_pending_dir` (une
    archive déjà extraite a été déplacée hors de `dest_dir`, sans quoi
    elle serait retéléchargée à chaque passage — voir `known_modio_ids`,
    et le même principe côté Nexus dans `download_mods_from_links_file`).
    Sans ce contrôle, le fichier retéléchargé prend un nom légèrement
    différent une fois déplacé dans `archives_installed_dir` (suffixe
    "(1)", "(2)"... ajouté par `_unique_destination` car le nom d'origine
    y existe déjà) : symptôme observé de véritables archives dupliquées,
    pas seulement des .pak (voir `extract_archives_to_mods`, qui lui ne
    duplique plus que le contenu .pak, pas l'archive).

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

    already_present_ids = known_modio_ids(
        dest_dir, *(d for d in (archives_installed_dir, archives_pending_dir) if d is not None)
    )

    for mod in mods:
        if mod.mod_id in already_present_ids:
            log(fmt_row(mod.name, STATUS_IGNORE, detail="déjà présent"))
            report["skipped"].append(mod.name)
            continue

        if not mod.download_url:
            log(fmt_row(mod.name, STATUS_ECHEC, detail="pas de fichier disponible"))
            report["failed"].append((mod.name, "pas de fichier disponible"))
            continue

        # mod.io sert tous les téléchargements depuis une URL générique
        # (littéralement `.../download`, sans nom de fichier) : sans nom de
        # secours distinctif, tous les mods sans Content-Disposition
        # résoudraient au même nom de fichier et se feraient passer pour
        # des doublons les uns des autres (voir `downloader._resolve_filename`).
        fallback_stem = f"{mod.name}-modio{mod.mod_id}"

        try:
            target_name = resolve_remote_filename(mod.download_url, fallback_stem=fallback_stem)
        except Exception as exc:
            log(fmt_row(mod.name, STATUS_ECHEC, detail=f"URL invalide : {exc}"))
            report["failed"].append((mod.name, str(exc)))
            continue

        if (dest_dir / target_name).exists():
            log(fmt_row(mod.name, STATUS_IGNORE, detail="déjà présent"))
            report["skipped"].append(mod.name)
            continue

        try:
            path = download_file(mod.download_url, dest_dir, fallback_stem=fallback_stem)
            log(fmt_row(mod.name, STATUS_SUCCES, detail=path.name))
            report["downloaded"].append(mod.name)
        except Exception as exc:
            log(fmt_row(mod.name, STATUS_ECHEC, detail=str(exc)))
            report["failed"].append((mod.name, str(exc)))

    return report


# Suffixe de doublon "(N)" ajouté en fin de nom (avant l'extension) par
# `_unique_destination` (déplacement d'une archive vers `_installees`/
# `_a_traiter`) ou par un navigateur lors d'un second téléchargement manuel
# du même fichier — voir `known_modio_ids`/`inventory._DUPLICATE_SUFFIX_RE`
# pour la même convention côté détection d'ID.
_DUPLICATE_SUFFIX_RE = re.compile(r" \(\d+\)(\.[A-Za-z0-9]+)$")

_HASH_CHUNK_SIZE = 1024 * 1024


def _file_hash(path: Path) -> str:
    """Hash SHA-256 du contenu de `path`, lu par blocs (pas de chargement
    intégral en mémoire — les archives de mods peuvent être volumineuses)."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _human_size(size_bytes: int) -> str:
    """Formate une taille en octets en unité lisible (o/Ko/Mo/Go), pour les
    logs de `cleanup_duplicate_archives`."""
    size = float(size_bytes)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{int(size)} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} Go"


def cleanup_duplicate_archives(
    directory: Path,
    *,
    log: LogFn = lambda _msg: None,
) -> dict[str, list | int]:
    """Détecte et supprime, dans `directory`, les archives en doublon d'un
    même mod téléchargé/installé plusieurs fois au fil du temps — le
    symptôme typique observé dans `_installees` : des triplets comme
    "Aesir's Champion Set-modio5990151.zip",
    "Aesir's Champion Set-modio5990151 (1).zip",
    "Aesir's Champion Set-modio5990151 (2).zip" (voir cause racine dans
    `download_subscribed_modio_mods` : un mod déjà installé, non détecté
    comme tel, était retéléchargé puis, une fois déplacé vers
    `_installees` par `extract_archives_to_mods`, suffixé "(N)" par
    `_unique_destination` car le nom d'origine y était déjà pris).

    Un "doublon potentiel" regroupe les archives dont le nom, une fois le
    suffixe " (N)" final retiré, est identique (`_DUPLICATE_SUFFIX_RE`).
    Pour éviter de supprimer par erreur une variante réellement
    différente qui partagerait ce même nom de base (ex: une mise à jour du
    mod retéléchargée sous un nom suffixé, dont le contenu a changé — se
    fier à la seule taille ne suffit pas à l'exclure), seules les archives
    dont le contenu est strictement identique (hash SHA-256) au sein d'un
    même groupe sont traitées comme de vrais doublons : parmi elles, la
    plus ancienne (`st_mtime`) est conservée, les autres supprimées. Un
    groupe de même nom de base mais de hash différents n'est PAS touché
    (compté comme "conflit", à examiner manuellement).

    Retourne {"removed": [nom, ...], "freed_bytes": int, "conflicts":
    [nom_de_base, ...]}."""
    report: dict[str, list | int] = {"removed": [], "freed_bytes": 0, "conflicts": []}
    if not directory.is_dir():
        return report

    groups: dict[str, list[Path]] = {}
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() not in (".zip", ".rar", ".7z"):
            continue
        base_name = _DUPLICATE_SUFFIX_RE.sub(r"\1", path.name)
        groups.setdefault(base_name, []).append(path)

    removed: list[str] = []
    conflicts: list[str] = []
    freed = 0

    for base_name, paths in groups.items():
        if len(paths) < 2:
            continue

        by_hash: dict[str, list[Path]] = {}
        for path in paths:
            by_hash.setdefault(_file_hash(path), []).append(path)

        if len(by_hash) > 1:
            conflicts.append(base_name)
            log(
                fmt_row(
                    base_name,
                    STATUS_EXAMEN,
                    detail=f"{len(by_hash)} versions distinctes de contenu — conservées telles quelles",
                )
            )
            continue

        (dups,) = by_hash.values()
        dups.sort(key=lambda p: p.stat().st_mtime)
        keep, extra = dups[0], dups[1:]
        for path in extra:
            size = path.stat().st_size
            path.unlink()
            freed += size
            removed.append(path.name)
            log(
                fmt_row(
                    path.name,
                    STATUS_IGNORE,
                    detail=f"doublon de {keep.name} ({_human_size(size)} récupéré(s))",
                )
            )

    report["removed"] = removed
    report["freed_bytes"] = freed
    report["conflicts"] = conflicts
    log(
        f"Nettoyage des doublons ({directory.name}) : {len(removed)} archive(s) "
        f"supprimée(s) ({_human_size(freed)} récupéré(s)), {len(conflicts)} conflit(s) ignoré(s)."
    )
    return report


def _protected_inodes(managed_native_dir: Path | None) -> set[tuple[int, int]]:
    """(st_dev, st_ino) de chaque fichier sous `managed_native_dir` — sert
    à repérer, parmi les .pak de Mods/, ceux qui sont en réalité des
    hardlinks vers un mod natif géré (voir `native_mods.py`) plutôt que
    de simples .pak copiés par `extract_archives_to_mods`."""
    if managed_native_dir is None or not managed_native_dir.is_dir():
        return set()
    inodes = set()
    for path in managed_native_dir.rglob("*"):
        if path.is_file():
            stat = path.stat()
            inodes.add((stat.st_dev, stat.st_ino))
    return inodes


def clean_pak_files(
    mods_dir: Path,
    *,
    native_mods_managed_dir: Path | None = None,
    log: LogFn = lambda _msg: None,
) -> list[str]:
    """Supprime les fichiers .pak présents directement dans `mods_dir`,
    sauf ceux qui sont des hardlinks vers un mod natif géré
    (`native_mods_managed_dir`, voir `native_mods.py`) — les supprimer
    romprait le lien sans que le manifeste ne le recrée automatiquement au
    prochain passage (il ne retraite que les archives encore en attente)."""
    if not mods_dir.is_dir():
        log(f"Dossier Mods introuvable : {mods_dir}")
        return []
    protected = _protected_inodes(native_mods_managed_dir)
    removed = []
    kept = 0
    for pak in mods_dir.glob("*.pak"):
        stat = pak.stat()
        if (stat.st_dev, stat.st_ino) in protected:
            kept += 1
            log(f"Conservé (mod natif) : {pak.name}")
            continue
        pak.unlink()
        removed.append(pak.name)
        log(f"Supprimé : {pak.name}")
    log(f"{len(removed)} fichier(s) .pak supprimé(s), {kept} conservé(s) (mods natifs).")
    return removed


def _merge_copy_tree(src: Path, dst: Path) -> int:
    """Copie récursivement le contenu de `src` dans `dst`, fusionnant avec
    ce qui existe déjà (les fichiers de même nom sont écrasés — c'est le
    comportement attendu pour combiner plusieurs mods "loose files" qui
    partagent une même arborescence, ex: Public/.../Generated/...).
    Retourne le nombre de fichiers copiés."""
    count = 0
    for item in src.rglob("*"):
        if item.is_dir():
            continue
        target = dst / item.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        count += 1
    return count


# Sous-dossiers connus de Data/ dans une installation BG3 : un mod "loose
# files" fournit typiquement l'un d'eux tel quel (ex: Generated/ pour un
# fichier stats généré, ou Public/ dont l'arborescence interne peut
# elle-même contenir des dossiers Generated/ plus profonds — voir Double
# XP: Public/Shared/Stats/Generated/Data/XPData.txt). Il faut préserver
# toute la structure sous ce dossier plutôt que de chercher "Generated"
# n'importe où et l'aplatir, sous peine de faire collisionner des
# fichiers de même nom venant de sous-arborescences différentes.
_DATA_ROOT_DIR_NAMES = {
    "generated",
    "public",
    "localization",
    "editor",
    "mods",
    "video",
    "fonts",
}


def _find_loose_file_roots(extracted_root: Path) -> list[Path]:
    """Repère, à la racine de `extracted_root` (après avoir traversé les
    éventuels dossiers d'enrobage — beaucoup d'archives placent tout sous
    un seul dossier portant le nom du mod), les dossiers correspondant à
    un sous-dossier connu de Data/ (voir `_DATA_ROOT_DIR_NAMES`)."""
    root = extracted_root
    while True:
        entries = [p for p in root.iterdir() if not p.name.startswith(".")]
        if (
            len(entries) == 1
            and entries[0].is_dir()
            and entries[0].name.lower() not in _DATA_ROOT_DIR_NAMES
        ):
            root = entries[0]
            continue
        break
    return [p for p in root.iterdir() if p.is_dir() and p.name.lower() in _DATA_ROOT_DIR_NAMES]


def extract_archives_to_mods(
    archives_dir: Path,
    mods_dir: Path,
    pending_dir: Path,
    installed_dir: Path,
    *,
    loose_mods_dir: Path | None = None,
    game_data_dir: Path | None = None,
    native_mods_manifest_path: Path | None = None,
    native_mods_managed_dir: Path | None = None,
    managed_dir: Path | None = None,
    select_nested_archives: SelectNestedArchivesFn | None = None,
    log: LogFn = lambda _msg: None,
) -> dict[str, list]:
    """Extrait chaque archive de `archives_dir` : les .pak trouvés sont
    copiés (à plat) dans `mods_dir`, puis l'archive traitée est déplacée
    dans `installed_dir`.

    Certains mods sont distribués sous forme d'une archive contenant elle-
    même d'autres archives (.zip/.rar/.7z, ex: plusieurs variantes d'un
    mod, ou un installeur qui embarque plusieurs add-ons) plutôt que des
    .pak directement. Quand `extract_archive` révèle de tels ZIP imbriqués
    dans le dossier temporaire d'extraction, `select_nested_archives` est
    appelé (avec le nom de l'archive parente et la liste de leurs chemins)
    pour demander lesquels garder — réutilise le même principe de choix
    que `select_files` dans `download_mods_from_links_file`. Ceux retenus
    sont à leur tour extraits (dans un sous-dossier dédié) et leur contenu
    rejoint la suite du traitement normal (recherche de .pak, puis de
    dossiers Data/ connus, ci-dessous) ; les autres sont simplement
    ignorés. Une seule profondeur d'imbrication est gérée (un ZIP imbriqué
    dans un ZIP imbriqué n'est pas redétecté) : ce cas n'a pas été observé
    en pratique et gérer une récursion illimitée ajouterait un risque
    d'archive-bombe pour un bénéfice hypothétique.

    Sans `select_nested_archives` (contexte non interactif), tous les ZIP
    imbriqués trouvés sont conservés et extraits — comme
    `download_mods_from_links_file` télécharge toutes les variantes
    candidates sans `select_files` : par défaut on préfère ne rien perdre
    silencieusement plutôt qu'écarter un contenu potentiellement utile
    sans que personne n'ait pu se prononcer.

    Si aucune .pak n'est trouvée mais qu'un sous-dossier connu de Data/
    (Generated, Public, ...) est présent — mods "loose files" — sa structure
    est d'abord fusionnée dans `loose_mods_dir` (notre copie gérée et
    permanente, qui combine les dossiers de plusieurs mods), puis reliée par
    hardlink dans `game_data_dir` (l'installation réelle du jeu). Nécessite
    `loose_mods_dir` et `game_data_dir` ; sinon ce cas est traité comme les
    autres mods non reconnus (voir ci-dessous).

    Si l'archive (par son nom exact) est décrite dans le manifeste des
    mods natifs (`native_mods_manifest_path`), elle est déployée comme mod
    DLL (voir `native_mods.deploy_native_mod_archive`) plutôt que d'être
    mise en attente — nécessite `native_mods_managed_dir` et `managed_dir`.
    Le même manifeste est aussi utilisé pour rattraper les archives déjà
    mises en attente lors d'un passage précédent (`_a_traiter`) mais
    entre-temps décrites dans le manifeste : elles sont déployées et
    déplacées vers `installed_dir` en fin de fonction.

    Si rien de tout ça n'est trouvé, l'archive est déplacée telle quelle
    dans `pending_dir` pour examen manuel.

    Un .pak dont le nom existe déjà dans `mods_dir` n'est pas copié en
    doublon (avec un suffixe "(1)") : il est ignoré, pour ne pas se
    retrouver avec deux fois le même mod (ex: extraction relancée deux
    fois sur la même archive, ou archive contenant un .pak déjà installé
    sous un autre biais). Si tous les .pak d'une archive sont ainsi déjà
    présents, l'archive est tout de même déplacée vers `installed_dir`
    (rien à en tirer de plus dans `archives_dir`).

    Retourne {"installed": [...], "pending": [...], "skipped": [...],
    "failed": [(name, err)]}.
    """
    mods_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, list] = {"installed": [], "pending": [], "skipped": [], "failed": []}

    can_handle_native = native_mods_manifest_path is not None and native_mods_managed_dir is not None and managed_dir is not None
    native_manifest: dict[str, str] = {}
    if can_handle_native:
        try:
            native_manifest = load_native_mods_manifest(native_mods_manifest_path)
        except NativeModsManifestError as exc:
            log(f"[#C46F6F]Manifeste des mods natifs ignoré : {exc}[/#C46F6F]")
            can_handle_native = False

    def _try_deploy_native(archive_path: Path) -> bool:
        """Si `archive_path` correspond à une entrée du manifeste des mods
        natifs, la déploie et la déplace vers `installed_dir`. Retourne
        True si traitée (succès ou échec journalisé), False si aucune
        entrée ne correspond (l'appelant doit alors continuer normalement)."""
        relative_dest = native_manifest.get(archive_path.name)
        if relative_dest is None:
            return False
        try:
            deploy_native_mod_archive(
                archive_path,
                relative_dest,
                managed_native_dir=native_mods_managed_dir,
                managed_dir=managed_dir,
                log=log,
            )
        except (NativeModsManifestError, ArchiveError) as exc:
            log(fmt_row(archive_path.name, STATUS_ECHEC, detail=str(exc)))
            report["failed"].append((archive_path.name, str(exc)))
            return True
        log(fmt_row(archive_path.name, STATUS_SUCCES, detail="mod DLL déployé (manifest natif)"))
        dest = _unique_destination(installed_dir, archive_path.name)
        shutil.move(str(archive_path), str(dest))
        report["installed"].append(archive_path.name)
        return True

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
        if can_handle_native and _try_deploy_native(archive):
            continue

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

            nested_archives = [
                p for p in tmp_path.rglob("*") if p.is_file() and is_supported_archive(p)
            ]
            if nested_archives:
                if select_nested_archives is not None:
                    chosen = [p for p in select_nested_archives(archive.name, nested_archives) if p in nested_archives]
                else:
                    chosen = list(nested_archives)
                rejected = [p for p in nested_archives if p not in chosen]

                if rejected:
                    names = ", ".join(p.name for p in rejected)
                    log(fmt_row(archive.name, STATUS_IGNORE, detail=f"ZIP imbriqué(s) ignoré(s) : {names}"))

                if chosen:
                    names = ", ".join(p.name for p in chosen)
                    log(fmt_row(archive.name, STATUS_SUCCES, detail=f"ZIP imbriqué(s) retenu(s) : {names}"))
                    for nested in chosen:
                        nested_dest = nested.parent / f"_imbrique_{nested.stem}"
                        try:
                            extract_archive(nested, nested_dest)
                        except ArchiveError as exc:
                            log(fmt_row(nested.name, STATUS_ECHEC, detail=f"ZIP imbriqué non extrait : {exc}"))

            paks = list(tmp_path.rglob("*.pak"))
            if paks:
                new_paks = [pak for pak in paks if not (mods_dir / pak.name).exists()]
                duplicate_paks = [pak for pak in paks if pak not in new_paks]
                for pak in new_paks:
                    shutil.copy2(pak, mods_dir / pak.name)

                if new_paks:
                    detail = f"{len(new_paks):>2} .pak installé(s)"
                    if duplicate_paks:
                        detail += f", {len(duplicate_paks)} déjà présent(s) ignoré(s)"
                    log(fmt_row(archive.name, STATUS_SUCCES, detail=detail))
                    report["installed"].append(archive.name)
                else:
                    log(
                        fmt_row(
                            archive.name,
                            STATUS_IGNORE,
                            detail=f"{len(duplicate_paks):>2} .pak déjà présent(s), rien à installer",
                        )
                    )
                    report["skipped"].append(archive.name)

                dest = _unique_destination(installed_dir, archive.name)
                shutil.move(str(archive), str(dest))
                continue

            can_handle_loose = loose_mods_dir is not None and game_data_dir is not None
            loose_roots = _find_loose_file_roots(tmp_path) if can_handle_loose else []
            if loose_roots:
                copied = sum(
                    _merge_copy_tree(root, loose_mods_dir / root.name) for root in loose_roots
                )
                linked = deploy_loose_files(loose_mods_dir, game_data_dir, log=log)
                names = ", ".join(f"Data/{root.name}" for root in loose_roots)
                log(
                    fmt_row(
                        archive.name,
                        STATUS_SUCCES,
                        detail=(
                            f"{copied} fichier(s) loose ({names}) géré(s) et "
                            f"reliés (hardlink) dans Data/ ({linked} au total)"
                        ),
                    )
                )
                dest = _unique_destination(installed_dir, archive.name)
                shutil.move(str(archive), str(dest))
                report["installed"].append(archive.name)
                continue

            log(fmt_row(archive.name, STATUS_EXAMEN, detail="aucun .pak ni dossier Data/ reconnu trouvé"))
            dest = _unique_destination(pending_dir, archive.name)
            shutil.move(str(archive), str(dest))
            report["pending"].append(archive.name)

    # Rattrapage : des archives déjà mises en attente lors d'un passage
    # précédent peuvent depuis avoir été décrites dans le manifeste des
    # mods natifs (ex: après avoir vu le nom exact du fichier téléchargé,
    # variable d'un téléchargement à l'autre — impossible à deviner avant).
    if can_handle_native and pending_dir.is_dir():
        for archive_name in list(native_manifest):
            archive_path = pending_dir / archive_name
            if archive_path.is_file():
                _try_deploy_native(archive_path)
                report["pending"] = [n for n in report["pending"] if n != archive_name]

    return report
