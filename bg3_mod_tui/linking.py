"""Mise en place des liens entre le dossier géré du TUI et les dossiers BG3
dans l'AppData de l'utilisateur.

Étapes réalisées par `setup_links()` :
1. Créer, dans le dossier géré (`BG3_Managed/`), un lien symbolique `Mods`
   pointant vers le dossier `Mods/` réel de BG3 dans l'AppData — permet au
   TUI de déposer les mods téléchargés sans naviguer dans l'AppData.
2. Copier `modsettings.lsx` (AppData -> dossier géré) pour en faire la copie
   de référence éditée par le TUI.
3. Remplacer le `modsettings.lsx` de l'AppData par un hardlink vers notre
   copie gérée, afin que les deux restent en permanence synchronisés (même
   fichier sur le disque, deux chemins).
4. Créer, dans le dossier géré, un lien symbolique `Installation BG3`
   pointant vers le dossier d'installation du jeu — permet d'accéder
   rapidement à bin/ (ex: NativeMods/, DLL du Script Extender) sans
   naviguer jusqu'à l'installation Steam.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from bg3_mod_tui.config import ModToolsConfig
from bg3_mod_tui.platform_utils import can_create_links_without_admin, is_windows


class LinkingError(RuntimeError):
    """Erreur récupérable lors de la mise en place des liens (ex : droits
    insuffisants). Le message est destiné à être affiché à l'utilisateur."""


@dataclass
class LinkingReport:
    steps: list[str]

    def add(self, message: str) -> None:
        self.steps.append(message)


def _create_symlink(link_path: Path, target: Path, *, target_is_dir: bool) -> None:
    try:
        if link_path.is_symlink() or link_path.exists():
            if link_path.is_symlink() and link_path.resolve() == target.resolve():
                return
            raise LinkingError(
                f"'{link_path}' existe déjà et n'est pas le lien attendu. "
                "Supprime-le ou renomme-le avant de relancer la configuration."
            )
        link_path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link_path, target_is_directory=target_is_dir)
    except OSError as exc:
        if is_windows() and not can_create_links_without_admin():
            raise LinkingError(
                "Impossible de créer le lien symbolique : privilèges "
                "administrateur requis sur Windows (ou active le mode "
                "développeur dans les Paramètres Windows)."
            ) from exc
        raise LinkingError(f"Échec de création du lien symbolique : {exc}") from exc


def _replace_with_hardlink(original: Path, source: Path) -> None:
    backup = original.with_suffix(original.suffix + ".bak")
    try:
        if original.exists() and not original.is_symlink():
            # Si déjà un hardlink vers la même donnée (même inode), rien à faire.
            if original.stat().st_ino == source.stat().st_ino:
                return
            if not backup.exists():
                shutil.move(str(original), str(backup))
            else:
                original.unlink()
        os.link(source, original)
    except OSError as exc:
        raise LinkingError(f"Échec de création du hardlink modsettings.lsx : {exc}") from exc


def setup_links(config: ModToolsConfig) -> LinkingReport:
    """Met en place la structure de liens décrite en en-tête de module.

    Lève `LinkingError` en cas de problème (droits insuffisants, structure
    AppData inattendue, etc.) avec un message destiné à l'utilisateur.
    """
    report = LinkingReport(steps=[])

    if is_windows() and not can_create_links_without_admin():
        raise LinkingError(
            "Privilèges administrateur requis sur Windows pour créer des "
            "liens symboliques et des liens physiques. Relance le "
            "programme en tant qu'administrateur, ou active le mode "
            "développeur Windows."
        )

    appdata_mods_dir = config.appdata_mods_dir
    if not appdata_mods_dir.is_dir():
        raise LinkingError(
            f"Le dossier Mods attendu est introuvable : '{appdata_mods_dir}'. "
            "Vérifie l'emplacement AppData de BG3 renseigné."
        )

    config.managed_dir.mkdir(parents=True, exist_ok=True)

    # 1. Lien symbolique vers le dossier Mods/ de l'AppData.
    _create_symlink(config.managed_mods_link, appdata_mods_dir, target_is_dir=True)
    report.add(f"Lien symbolique créé : {config.managed_mods_link} -> {appdata_mods_dir}")

    # 2. Copie de référence de modsettings.lsx dans le dossier géré.
    appdata_modsettings = config.appdata_modsettings_path
    managed_modsettings = config.managed_modsettings_path
    if not managed_modsettings.exists():
        if not appdata_modsettings.exists():
            raise LinkingError(
                f"'{appdata_modsettings}' introuvable : impossible de "
                "récupérer la configuration de mods existante."
            )
        managed_modsettings.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(appdata_modsettings, managed_modsettings)
        report.add(f"Copie créée : {managed_modsettings}")
    else:
        report.add(f"Copie de référence déjà présente : {managed_modsettings}")

    # 3. Remplacement du modsettings.lsx AppData par un hardlink vers la copie gérée.
    _replace_with_hardlink(appdata_modsettings, managed_modsettings)
    report.add(f"Hardlink en place : {appdata_modsettings} <-> {managed_modsettings}")

    # 4. Lien symbolique vers le dossier d'installation du jeu.
    install_dir = config.install_path
    if not install_dir.is_dir():
        raise LinkingError(
            f"Le dossier d'installation BG3 attendu est introuvable : '{install_dir}'. "
            "Vérifie l'emplacement d'installation renseigné."
        )
    _create_symlink(config.managed_install_link, install_dir, target_is_dir=True)
    report.add(f"Lien symbolique créé : {config.managed_install_link} -> {install_dir}")

    return report
