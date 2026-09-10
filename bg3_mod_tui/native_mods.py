"""Déploiement des mods « natifs » (DLL) qui n'ont pas de .pak et ne
peuvent donc pas être traités par `extract_archives_to_mods` — ils
finissent dans `_a_traiter` en attente d'un traitement manuel.

Beaucoup de ces mods (ex: Native Camera Tweaks) sont de simples DLL à
déposer dans un sous-dossier de bin/ (le plus souvent `bin/NativeMods/`,
chargé par Native Mod Loader). Plutôt que de les traiter à la main, on
décrit chaque mod dans un petit manifeste JSON édité à la main, avec un
chemin relatif au dossier géré `BG3_Managed/` (et non à l'installation du
jeu directement) :

    {
        "Native Camera Tweaks-945-2-4-5-1758665322.zip": "Installation BG3/bin/NativeMods"
    }

`deploy_native_mods_from_manifest` extrait alors l'archive correspondante
(trouvée dans `_a_traiter`) vers un stockage géré permanent — nécessaire
car un hardlink ne peut pas survivre à la suppression de son fichier
source, contrairement à une simple copie — puis relie par hardlink chaque
fichier extrait vers `<managed_dir>/<chemin du manifeste>`. Passer par
`managed_dir` (BG3_Managed) plutôt que par l'installation du jeu
directement limite l'écriture aux seuls dossiers déjà exposés par
`setup_links()` (le lien symbolique `Installation BG3`, `Mods`) : aucune
« promenade » ailleurs sur le système n'est possible via ce chemin.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from bg3_mod_tui.archives import ArchiveError, extract_archive

LogFn = Callable[[str], None]


class NativeModsManifestError(RuntimeError):
    """Erreur de lecture/format du manifeste — message destiné à l'utilisateur."""


def load_manifest(manifest_path: Path) -> dict[str, str]:
    """Charge le manifeste `{"<archive>": "<chemin relatif à BG3_Managed>"}`.
    Retourne un dict vide si le fichier n'existe pas encore."""
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeModsManifestError(
            f"Manifeste JSON invalide ({manifest_path.name}) : {exc}"
        ) from exc
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise NativeModsManifestError(
            f"Le manifeste ({manifest_path.name}) doit être un objet JSON "
            '"<archive>": "<chemin relatif>".'
        )
    return data


def _resolve_dest_dir(managed_dir: Path, relative_dest: str) -> Path:
    """Résout `relative_dest` sous `managed_dir` (BG3_Managed) : le
    dossier géré et ses liens symboliques (`Installation BG3`, `Mods`)
    sont les seules destinations permises — rejette tout chemin absolu ou
    contenant `..`, qui permettrait de sortir de cette arborescence vers
    le reste du système. Volontairement pas de `resolve()` ici : ça
    suivrait le symlink `Installation BG3` et ferait échouer la
    vérification d'appartenance à `managed_dir`."""
    relative = Path(relative_dest)
    if relative.is_absolute() or ".." in relative.parts:
        raise NativeModsManifestError(
            f"Chemin d'extraction refusé (doit rester sous BG3_Managed, sans '..') : "
            f"'{relative_dest}'."
        )
    return managed_dir / relative


def _hardlink_into(dest_dir: Path, source: Path, *, log: LogFn) -> None:
    target = dest_dir / source.name
    if target.exists():
        if target.stat().st_ino == source.stat().st_ino:
            log(f"  '{target.name}' déjà relié vers '{source}', rien à faire.")
            return
        target.unlink()
    os.link(source, target)
    log(f"  '{target.name}' relié (hardlink) vers {dest_dir}.")


def deploy_native_mod_archive(
    archive_path: Path,
    relative_dest: str,
    *,
    managed_native_dir: Path,
    managed_dir: Path,
    log: LogFn = lambda _msg: None,
) -> int:
    """Extrait `archive_path` vers `managed_native_dir` (stockage
    permanent) puis relie par hardlink chaque fichier extrait vers
    `relative_dest` sous `managed_dir` (voir `_resolve_dest_dir` pour la
    restriction d'accès). Ne déplace PAS `archive_path` lui-même — le
    point de départ diffère selon l'appelant (archive fraîche ou déjà
    dans `_a_traiter`), donc ce choix reste à sa charge. Retourne le
    nombre de fichiers reliés. Lève `NativeModsManifestError` (chemin
    refusé) ou `ArchiveError` (échec d'extraction, y compris archive
    extraite vide)."""
    dest_dir = _resolve_dest_dir(managed_dir, relative_dest)

    extract_dir = managed_native_dir / archive_path.stem
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_archive(archive_path, extract_dir)

    files = [p for p in extract_dir.rglob("*") if p.is_file()]
    if not files:
        raise ArchiveError(f"archive extraite vide : {archive_path.name}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    log(f"{archive_path.name} -> {dest_dir} ({len(files)} fichier(s))")
    for file in files:
        _hardlink_into(dest_dir, file, log=log)
    return len(files)


def deploy_native_mods_from_manifest(
    *,
    pending_dir: Path,
    installed_dir: Path,
    managed_native_dir: Path,
    managed_dir: Path,
    manifest_path: Path,
    log: LogFn = lambda _msg: None,
) -> dict[str, list]:
    """Traite chaque entrée du manifeste dont l'archive est présente dans
    `pending_dir` (voir `deploy_native_mod_archive`), et déplace l'archive
    traitée vers `installed_dir`.

    Retourne {"deployed": [...], "skipped": [...], "failed": [(name, err)]}.
    """
    report: dict[str, list] = {"deployed": [], "skipped": [], "failed": []}

    manifest = load_manifest(manifest_path)
    if not manifest:
        log(f"Manifeste vide ou introuvable : {manifest_path}")
        return report

    for archive_name, relative_dest in manifest.items():
        archive_path = pending_dir / archive_name
        if not archive_path.is_file():
            if (installed_dir / archive_name).is_file():
                # Déjà traitée par un passage précédent (déplacée vers
                # `installed_dir` en fin de fonction) — les fichiers restent
                # déployés (hardlinks persistants), rien à refaire. À
                # distinguer d'une archive jamais vue : "ignoré" pourrait
                # sinon laisser croire, à tort, que le mod natif n'est pas
                # (ou plus) déployé.
                log(f"IGNORÉ  {archive_name} : déjà déployé (voir {installed_dir.name}).")
            else:
                log(f"IGNORÉ  {archive_name} : absent de {pending_dir.name}.")
            report["skipped"].append(archive_name)
            continue

        try:
            deploy_native_mod_archive(
                archive_path,
                relative_dest,
                managed_native_dir=managed_native_dir,
                managed_dir=managed_dir,
                log=log,
            )
        except (NativeModsManifestError, ArchiveError) as exc:
            log(f"ÉCHEC   {archive_name} : {exc}")
            report["failed"].append((archive_name, str(exc)))
            continue

        dest_archive = installed_dir / archive_name
        installed_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(archive_path), str(dest_archive))
        report["deployed"].append(archive_name)

    return report
