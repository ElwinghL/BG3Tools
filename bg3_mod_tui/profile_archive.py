"""Export/import de profils de mods sous forme d'archive `.tar.zst`
autonome, pour les partager avec quelqu'un utilisant le même outil.

Contrairement à `profiles.py` (sauvegarde locale : ne garde que les *noms*
de fichiers, puisque Mods/ et bin/NativeMods/ sont déjà là), une archive
exportée embarque le contenu réel des .pak, des DLL de bin/NativeMods/ et
des fichiers "loose" de DataMods/, en plus de modsettings.lsx et du
manifeste (avec l'origine Nexus de chaque mod quand elle a pu être
retrouvée) — pour que l'import recrée le même profil chez quelqu'un
d'autre sans qu'il ait besoin de retélécharger quoi que ce soit.

Compression : zstandard niveau 19, multi-thread — bon compromis
ratio/temps ; les .pak sont déjà eux-mêmes compressés (gain modeste), les
DLL/loose files le sont rarement (gain plus net).

L'import recrée d'abord un profil local standard (mêmes dossiers gérés
que `save_profile`), puis appelle `restore_profile` pour l'activer —
aucune logique de déploiement n'est dupliquée."""

from __future__ import annotations

import json
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

import zstandard

from bg3_mod_tui.native_mods import load_manifest as load_native_mods_manifest
from bg3_mod_tui.profiles import (
    MANIFEST_FILENAME,
    MODSETTINGS_FILENAME,
    ProfileError,
    find_profile_dir,
    manifest_file_names,
    slugify_profile_name,
)

LogFn = Callable[[str], None]

# Niveau maximal (le plus compact possible) plutôt qu'un compromis
# vitesse/ratio : cette archive est écrite une fois pour être partagée,
# pas sur un chemin chaud — le temps de compression supplémentaire
# (nettement plus long qu'au niveau 19) est acceptable.
ZSTD_LEVEL = 22
ARCHIVE_SUFFIX = ".bg3profile.tar.zst"

MODS_ARCNAME = "Mods"
NATIVE_MODS_ARCNAME = "NativeMods"
LOOSE_MODS_ARCNAME = "DataMods"
NATIVE_MODS_MANIFEST_ARCNAME = "native_mods_manifest.json"
INVENTORY_ARCNAME = "mods_inventory.json"


class ProfileArchiveError(RuntimeError):
    """Erreur d'export/import — message destiné à l'utilisateur."""


def _load_native_mods_manifest_for_export(native_mods_manifest_path: Path) -> dict[str, str]:
    """Contenu intégral de `native_mods_manifest.json` (mapping archive ->
    destination sous BG3_Managed, voir `native_mods.py`), pas seulement le
    sous-ensemble utile à ce profil : embarqué tel quel pour que les deux
    machines finissent avec un manifeste identique après import (mêmes
    mods natifs connus, mêmes destinations) plutôt que de diverger au fil
    des échanges de profils — négligeable en taille face aux .pak/DLL déjà
    inclus, donc sans impact sur la compacité de l'archive."""
    try:
        return load_native_mods_manifest(native_mods_manifest_path)
    except Exception:
        return {}


def _add_json_file(tar: tarfile.TarFile, arcname: str, data: dict) -> None:
    """Ajoute `data` au tar sous `arcname` sans passer par un fichier
    temporaire sur disque (source déjà en mémoire, contrairement aux
    autres membres de l'archive qui sont de vrais fichiers ajoutés via
    `tar.add`)."""
    encoded = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    info = tarfile.TarInfo(arcname)
    info.size = len(encoded)
    tar.addfile(info, BytesIO(encoded))


def export_profile_archive(
    name: str,
    *,
    profiles_dir: Path,
    mods_dir: Path,
    loose_mods_dir: Path,
    native_mods_dir: Path,
    dest_path: Path,
    native_mods_manifest_path: Path | None = None,
    inventory_path: Path | None = None,
    log: LogFn = lambda _msg: None,
) -> Path:
    """Exporte le profil `name` (déjà sauvegardé via `save_profile`) vers
    une archive `.tar.zst` autonome sous `dest_path` : modsettings.lsx,
    manifeste, le contenu réel de chaque .pak (`mods_dir`), DLL
    (`native_mods_dir`) et fichier loose (`loose_mods_dir`) listé dans le
    manifeste. Si fournis, `native_mods_manifest_path`
    (`native_mods_manifest.json`) et `inventory_path`
    (`mods_inventory.json`) sont aussi embarqués intégralement (pas
    filtrés au profil) : l'objectif est que les deux machines finissent
    identiques après import, pas seulement le strict nécessaire au
    profil — ces deux fichiers sont de toute façon négligeables en taille
    face aux .pak/DLL déjà inclus. Un fichier attendu mais absent est
    journalisé et ignoré (pas d'échec global) — l'archive reste utile même
    incomplète."""
    try:
        profile_dir = find_profile_dir(profiles_dir, name)
    except ProfileError:
        raise
    manifest_path = profile_dir / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    compressor = zstandard.ZstdCompressor(level=ZSTD_LEVEL, threads=-1)

    included = 0
    missing = 0
    with dest_path.open("wb") as raw, compressor.stream_writer(raw) as zfh:
        with tarfile.open(fileobj=zfh, mode="w|") as tar:
            tar.add(profile_dir / MODSETTINGS_FILENAME, arcname=MODSETTINGS_FILENAME)
            tar.add(manifest_path, arcname=MANIFEST_FILENAME)

            for entries, source_dir, arc_root in (
                (manifest.get("paks", []), mods_dir, MODS_ARCNAME),
                (manifest.get("native_mods", []), native_mods_dir, NATIVE_MODS_ARCNAME),
            ):
                for file_name in sorted(manifest_file_names(entries)):
                    source = source_dir / file_name
                    if not source.is_file():
                        log(f"[#D8C091]Absent, ignoré : {source}[/#D8C091]")
                        missing += 1
                        continue
                    tar.add(source, arcname=f"{arc_root}/{file_name}")
                    included += 1

            for relative in sorted(manifest.get("loose_files", [])):
                source = loose_mods_dir / relative
                if not source.is_file():
                    log(f"[#D8C091]Absent, ignoré : {source}[/#D8C091]")
                    missing += 1
                    continue
                tar.add(source, arcname=f"{LOOSE_MODS_ARCNAME}/{relative}")
                included += 1

            if native_mods_manifest_path is not None:
                native_manifest = _load_native_mods_manifest_for_export(native_mods_manifest_path)
                if native_manifest:
                    _add_json_file(tar, NATIVE_MODS_MANIFEST_ARCNAME, native_manifest)
                    included += 1

            if inventory_path is not None and inventory_path.is_file():
                try:
                    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    log(f"[#D8C091]Inventaire ignoré (invalide) : {exc}[/#D8C091]")
                else:
                    _add_json_file(tar, INVENTORY_ARCNAME, inventory)
                    included += 1

    log(f"Archive créée : {dest_path} ({included} fichier(s), {missing} absent(s)).")
    return dest_path


def import_profile_archive(
    archive_path: Path,
    *,
    profiles_dir: Path,
    mods_dir: Path,
    loose_mods_dir: Path,
    native_mods_dir: Path,
    native_mods_manifest_path: Path | None = None,
    log: LogFn = lambda _msg: None,
) -> str:
    """Importe une archive créée par `export_profile_archive` : extrait
    son contenu vers les dossiers gérés (`mods_dir`, `native_mods_dir`,
    `loose_mods_dir`), puis enregistre le profil sous `profiles_dir` comme
    s'il avait été sauvegardé localement (mêmes modsettings.lsx +
    manifeste). Si l'archive embarque un `native_mods_manifest.json` (voir
    `_profile_native_mods_manifest`) et que `native_mods_manifest_path` est
    fourni, ses entrées sont fusionnées dans le manifeste local — sans
    écraser une entrée déjà présente (une éventuelle destination
    personnalisée localement prime). Ne l'active pas — l'appelant doit
    ensuite appeler `restore_profile` pour ça (même flux que pour un
    profil sauvegardé localement). Retourne le nom du profil importé. Lève
    `ProfileArchiveError` si l'archive est invalide."""
    if not archive_path.is_file():
        raise ProfileArchiveError(f"Archive introuvable : {archive_path}")

    with tempfile.TemporaryDirectory(prefix="bg3profile_import_") as tmp:
        tmp_path = Path(tmp)
        try:
            decompressor = zstandard.ZstdDecompressor()
            with archive_path.open("rb") as raw, decompressor.stream_reader(raw) as zfh:
                with tarfile.open(fileobj=zfh, mode="r|") as tar:
                    tar.extractall(tmp_path, filter="data")
        except (zstandard.ZstdError, tarfile.TarError, OSError) as exc:
            raise ProfileArchiveError(f"Archive invalide ou corrompue : {exc}") from exc

        manifest_path = tmp_path / MANIFEST_FILENAME
        modsettings_path = tmp_path / MODSETTINGS_FILENAME
        if not manifest_path.is_file() or not modsettings_path.is_file():
            raise ProfileArchiveError(
                f"Archive incomplète : {MANIFEST_FILENAME} ou {MODSETTINGS_FILENAME} manquant."
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        name = manifest.get("name") or archive_path.stem

        mods_dir.mkdir(parents=True, exist_ok=True)
        native_mods_dir.mkdir(parents=True, exist_ok=True)

        copied = 0
        for entries, source_root, target_dir in (
            (manifest.get("paks", []), tmp_path / MODS_ARCNAME, mods_dir),
            (manifest.get("native_mods", []), tmp_path / NATIVE_MODS_ARCNAME, native_mods_dir),
        ):
            for file_name in sorted(manifest_file_names(entries)):
                source = source_root / file_name
                if not source.is_file():
                    log(f"[#D8C091]Absent de l'archive, ignoré : {file_name}[/#D8C091]")
                    continue
                shutil.copy2(source, target_dir / file_name)
                copied += 1

        loose_source_root = tmp_path / LOOSE_MODS_ARCNAME
        for relative in sorted(manifest.get("loose_files", [])):
            source = loose_source_root / relative
            if not source.is_file():
                log(f"[#D8C091]Absent de l'archive, ignoré : {relative}[/#D8C091]")
                continue
            target = loose_mods_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1

        dest_dir = profiles_dir / slugify_profile_name(name)
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(modsettings_path, dest_dir / MODSETTINGS_FILENAME)
        shutil.copy2(manifest_path, dest_dir / MANIFEST_FILENAME)

        native_manifest_arc = tmp_path / NATIVE_MODS_MANIFEST_ARCNAME
        if native_mods_manifest_path is not None and native_manifest_arc.is_file():
            imported_entries = json.loads(native_manifest_arc.read_text(encoding="utf-8"))
            local_manifest = load_native_mods_manifest(native_mods_manifest_path)
            added = 0
            for archive_name, relative_dest in imported_entries.items():
                if archive_name not in local_manifest:
                    local_manifest[archive_name] = relative_dest
                    added += 1
            if added:
                native_mods_manifest_path.write_text(
                    json.dumps(local_manifest, indent=4, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                log(f"{added} entrée(s) ajoutée(s) à {native_mods_manifest_path.name}.")

    log(f"Profil « {name} » importé ({copied} fichier(s) copié(s)).")
    return name
