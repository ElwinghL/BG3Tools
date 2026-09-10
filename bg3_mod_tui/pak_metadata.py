"""Lecture de l'UUID/Name réels embarqués dans le `meta.lsx`/`meta.lsf` d'un
.pak — d'abord via le lecteur natif `pak_reader` (mmap + parsing Python pur
du format LSPK, sans sous-processus), avec repli automatique sur
Divine.exe (LSLib, voir `compat_framework.py` et Tools/ExportTools/) quand
la lecture native échoue (version LSPK/LSF non gérée par `pak_reader`,
fichier corrompu...) — voir `_read_pak_identity_native` et son usage dans
`read_pak_identity`.

Sert à identifier un mod de façon fiable — l'UUID de son `ModuleInfo` est
l'identifiant que le jeu lui-même utilise, indépendant du nom de fichier du
.pak ou de l'archive — là où `inventory._match_pak_to_archive` ne fait
qu'une association heuristique par sous-chaîne de nom, peu fiable dès que
le nom de fichier du .pak diverge de celui de l'archive (ex: préfixes
d'auteur, abréviations)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from xml.etree import ElementTree

from bg3_mod_tui.archives import ArchiveError, extract_archive
from bg3_mod_tui.compat_framework import find_divine_exe
from bg3_mod_tui.launcher import resolve_wine_bin
from bg3_mod_tui.pak_reader import (
    PakReaderError,
    extract_uuid_from_lsf_bytes,
    parse_meta_lsx_bytes,
    read_meta_lsx_or_lsf_bytes,
)
from bg3_mod_tui.platform_utils import find_proton_prefix, is_windows, to_wine_path

LogFn = Callable[[str], None]

# Le mod peut mettre plusieurs minutes à extraire pour les plus gros .pak
# (des Go d'assets) même en filtrant sur meta.lsx (`-x`) — Divine.exe doit
# quand même parcourir tout l'index du .pak avant de savoir quels fichiers
# correspondent au filtre.
_DIVINE_TIMEOUT_SECONDS = 120


class PakMetadataError(RuntimeError):
    """Échec de lecture des métadonnées d'un .pak — message utilisateur."""


def _run_divine(
    divine_exe: Path, args: list[str], *, reference_path: Path, timeout: float | None = None
) -> None:
    env = None
    if is_windows():
        command = [str(divine_exe), *args]
    else:
        prefix = find_proton_prefix(reference_path)
        if prefix is None:
            raise PakMetadataError("Impossible de déterminer le préfixe Proton de BG3.")
        wine_bin = resolve_wine_bin(prefix)
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix)
        command = [wine_bin, str(divine_exe), *args]

    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout if timeout is not None else _DIVINE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PakMetadataError(f"Timeout Divine.exe : {exc}") from exc
    except OSError as exc:
        raise PakMetadataError(f"Échec du lancement de Divine.exe : {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"code {result.returncode}"
        raise PakMetadataError(f"Échec Divine.exe : {detail}")


def _path_arg(path: Path, *, use_wine_path: bool) -> str:
    return to_wine_path(path) if use_wine_path else str(path)


def parse_meta_lsx(meta_path: Path) -> tuple[str, str] | None:
    """Extrait `(UUID, Name)` du nœud `ModuleInfo` (le descripteur du mod
    lui-même) d'un `meta.lsx`. Ignore volontairement tout UUID trouvé sous
    `Dependencies` (`ModuleShortDesc`, un identifiant qui ne serait pas
    celui de CE mod mais d'un de ses prérequis) en ciblant précisément le
    nœud `ModuleInfo` plutôt qu'une recherche brute sur tout le fichier.
    Retourne None si le fichier est invalide ou n'a pas d'UUID."""
    try:
        tree = ElementTree.parse(meta_path)
    except (ElementTree.ParseError, OSError):
        return None
    module_info = tree.find(".//node[@id='ModuleInfo']")
    if module_info is None:
        return None
    uuid = None
    name = None
    for attribute in module_info.findall("attribute"):
        attr_id = attribute.get("id")
        if attr_id == "UUID":
            uuid = attribute.get("value")
        elif attr_id == "Name":
            name = attribute.get("value")
    return (uuid, name or "") if uuid else None


def _read_pak_identity_native(pak_path: Path) -> tuple[str, str] | None:
    """Tente de lire `(UUID, Name)` directement depuis `pak_path` via
    `pak_reader` (mmap + parsing Python pur), sans sous-processus. Essaie
    `meta.lsx` (XML, UUID+Name fiables) puis, à défaut, `meta.lsf`
    (binaire, UUID seulement — voir la limite documentée sur
    `pak_reader.extract_uuid_from_lsf_bytes` : approche par regex, `Name`
    reste vide dans ce cas).

    Retourne None si le .pak est lisible nativement mais ne contient
    simplement aucun `meta.lsx`/`meta.lsf` exploitable (pas une erreur —
    équivalent au retour None historique de la voie Divine.exe). Laisse
    remonter `pak_reader.PakReaderError` (version LSPK/LSF non gérée,
    fichier corrompu...) : c'est le signal pour l'appelant de replier sur
    Divine.exe, pas un cas à absorber ici."""
    found = read_meta_lsx_or_lsf_bytes(pak_path)
    if found is None:
        return None
    kind, content = found
    if kind == "lsx":
        identity = parse_meta_lsx_bytes(content)
        if identity is None:
            return None
        uuid, name, _folder = identity
        return uuid, name
    # kind == "lsf" : seul l'UUID est extractible de façon fiable par
    # l'approche regex (voir pak_reader.extract_uuid_from_lsf_bytes) — pas
    # de Name, à la différence de la voie meta.lsx/Divine.exe.
    uuid = extract_uuid_from_lsf_bytes(content)
    return (uuid, "") if uuid else None


def read_pak_identity(
    pak_path: Path,
    *,
    divine_exe: Path,
    reference_path: Path,
    work_dir: Path,
) -> tuple[str, str] | None:
    """Retourne `(UUID, Name)` du mod contenu dans `pak_path`.

    Essaie d'abord la lecture native (`pak_reader`, rapide, sans
    sous-processus) — voir `_read_pak_identity_native`. Si celle-ci lève
    `PakReaderError` (version LSPK/LSF non gérée par `pak_reader`, .pak
    corrompu, structure inattendue...) *ou toute autre exception* (filet
    de sécurité : le format n'a pas pu être validé contre un vrai .pak
    BG3 dans l'environnement de développement de ce module, une hypothèse
    de format erronée pourrait donc lever autre chose qu'un
    `PakReaderError` propre), replie silencieusement sur Divine.exe
    (comportement historique, inchangé) : `work_dir` doit exister et être
    vide/dédié (nettoyé par l'appelant) dans ce cas.

    None si le .pak n'a pas de `meta.lsx`/`meta.lsf` exploitable (rare :
    mod purement "loose files" empaqueté à part) — que ce None vienne de
    la voie native ou du repli Divine.exe. Lève `PakMetadataError`
    uniquement si le repli Divine.exe lui-même échoue."""
    try:
        return _read_pak_identity_native(pak_path)
    except PakReaderError:
        pass  # cas prévu (version LSPK/LSF non gérée, .pak corrompu) -> repli Divine.exe
    except Exception:  # noqa: BLE001 - filet de sécurité volontairement large
        # `pak_reader` n'a jamais été validé contre un vrai .pak BG3 dans cet
        # environnement de développement (voir sa docstring) : une hypothèse de
        # format erronée pourrait lever un type d'exception non anticipé
        # (struct.error, IndexError, UnicodeDecodeError...) plutôt qu'un
        # PakReaderError propre. Mieux vaut replier silencieusement sur
        # Divine.exe dans ce cas que de faire planter tout l'appelant (scan
        # d'inventaire, résolution d'origine) pour un seul .pak récalcitrant —
        # cette tolérance disparaîtra si/quand le format est un jour validé
        # contre des .pak réels et que chaque cas d'échec est reclassé en
        # PakReaderError explicite ci-dessus.
        pass

    use_wine_path = not is_windows()
    _run_divine(
        divine_exe,
        [
            "-g", "bg3",
            "-a", "extract-package",
            "-s", _path_arg(pak_path, use_wine_path=use_wine_path),
            "-d", _path_arg(work_dir, use_wine_path=use_wine_path),
            "-x", "*meta.lsx",
        ],
        reference_path=reference_path,
    )
    matches = list(work_dir.rglob("meta.lsx"))
    if not matches:
        return None
    return parse_meta_lsx(matches[0])


def build_deployed_uuid_index(
    pak_paths: list[Path],
    *,
    divine_exe: Path,
    reference_path: Path,
    log: LogFn = lambda _msg: None,
) -> dict[str, str]:
    """UUID -> Name pour chaque .pak de `pak_paths` (typiquement tout
    `Mods/*.pak` actuellement déployé) — sert de référence pour
    déterminer si une archive correspond à un mod encore installé (voir
    `find_orphaned_archives_by_uuid`). Un .pak en échec est journalisé et
    ignoré (pas d'échec global)."""
    index: dict[str, str] = {}
    total = len(pak_paths)
    # Un par un si peu de .pak (retour visible à chaque étape), sinon un
    # intervalle qui garde des mises à jour fréquentes sans spammer sur
    # un gros Mods/ (voir même logique dans la boucle de vérification des
    # archives, run_orphaned_archives).
    step = 1 if total <= 20 else 10
    with tempfile.TemporaryDirectory(prefix="bg3_pak_meta_") as tmp:
        tmp_path = Path(tmp)
        for count, pak in enumerate(pak_paths, start=1):
            if step == 1 or count % step == 1 or count == total:
                log(f"  [{count}/{total}] {pak.name}...")
            work_dir = tmp_path / str(count)
            work_dir.mkdir()
            try:
                identity = read_pak_identity(
                    pak, divine_exe=divine_exe, reference_path=reference_path, work_dir=work_dir
                )
            except PakMetadataError as exc:
                log(f"[#D8C091]{pak.name} : {exc}[/#D8C091]")
                identity = None
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)
            if identity:
                index[identity[0]] = identity[1] or pak.stem
    return index


def archive_pak_identities(
    archive_path: Path,
    *,
    divine_exe: Path,
    reference_path: Path,
    log: LogFn = lambda _msg: None,
) -> list[tuple[str, str]]:
    """Identités `(UUID, Name)` de chaque .pak contenu dans `archive_path`
    (zip/rar/7z) — extrait l'archive entière dans un dossier temporaire
    (contrairement à `read_pak_identity`, pas de filtre possible avant de
    savoir où se trouve le/les .pak à l'intérieur), puis lit le meta.lsx de
    chaque .pak trouvé. Liste vide si l'archive ne contient aucun .pak
    (loose files) ou si l'extraction/lecture échoue (journalisé)."""
    identities: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="bg3_archive_meta_") as tmp:
        tmp_path = Path(tmp)
        try:
            extract_archive(archive_path, tmp_path)
        except ArchiveError as exc:
            log(f"[#D8C091]{archive_path.name} : {exc}[/#D8C091]")
            return identities

        for index, pak in enumerate(sorted(tmp_path.rglob("*.pak"))):
            work_dir = tmp_path / f"_meta_{index}"
            work_dir.mkdir()
            try:
                identity = read_pak_identity(
                    pak, divine_exe=divine_exe, reference_path=reference_path, work_dir=work_dir
                )
            except PakMetadataError as exc:
                log(f"[#D8C091]{archive_path.name} ({pak.name}) : {exc}[/#D8C091]")
                identity = None
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)
            if identity:
                identities.append(identity)
    return identities
