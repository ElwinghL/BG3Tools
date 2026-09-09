"""Configuration persistante du TUI (chemins BG3, dossiers gérés)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import tomlkit

CONFIG_PATH = Path(__file__).resolve().parent.parent / "bg3modtools.toml"
MANAGED_DIR_NAME = "BG3_Managed"

MODS_SUBDIR = "Mods"
PLAYER_PROFILES_MODSETTINGS = Path("PlayerProfiles") / "Public" / "modsettings.lsx"

TOOLS_DIR_NAME = "Tools"
ARCHIVES_DIR_NAME = "Archives_installees"
ARCHIVES_PENDING_SUBDIR = "_a_traiter"
ARCHIVES_INSTALLED_SUBDIR = "_installees"
NEXUS_LINKS_FILE_NAME = "nexus_links_to_add.md"
TOOLS_MD_FILE_NAME = "TOOLS.md"
NATIVE_MODS_MANIFEST_FILE_NAME = "native_mods_manifest.json"
NATIVE_MODS_MANAGED_SUBDIR = "NativeMods"
LOOSE_MODS_MANAGED_SUBDIR = "DataMods"
PROFILES_MANAGED_SUBDIR = "Profiles"


@dataclass
class ModToolsConfig:
    bg3_install_dir: str = ""
    bg3_appdata_dir: str = ""
    active_profile: str = ""
    # Adresse publique (URL) pour joindre cette machine, et son port —
    # demandées une première fois au lancement du script ; seront
    # re-demandées si absentes lors du clic sur le futur bouton "Web"
    # (fonctionnalité pas encore implémentée).
    public_url: str = ""
    public_port: str = ""

    @property
    def install_path(self) -> Path:
        return Path(self.bg3_install_dir)

    @property
    def game_bin_dir(self) -> Path:
        return self.install_path / "bin"

    @property
    def game_data_dir(self) -> Path:
        """Dossier Data/ du jeu — destination des mods "loose files" (ex:
        un dossier Generated/ à fusionner dedans), par opposition aux .pak
        qui vont dans Mods/."""
        return self.install_path / "Data"

    @property
    def appdata_path(self) -> Path:
        return Path(self.bg3_appdata_dir)

    @property
    def appdata_mods_dir(self) -> Path:
        return self.appdata_path / MODS_SUBDIR

    @property
    def appdata_modsettings_path(self) -> Path:
        return self.appdata_path / PLAYER_PROFILES_MODSETTINGS

    @property
    def managed_dir(self) -> Path:
        return CONFIG_PATH.parent / MANAGED_DIR_NAME

    @property
    def managed_mods_link(self) -> Path:
        return self.managed_dir / MODS_SUBDIR

    @property
    def managed_install_link(self) -> Path:
        return self.managed_dir / "Installation BG3"

    @property
    def managed_modsettings_path(self) -> Path:
        return self.managed_dir / "modsettings.lsx"

    @property
    def logs_dir(self) -> Path:
        return self.managed_dir / "logs"

    @property
    def web_root_dir(self) -> Path:
        """Racine servie par le serveur Web (bouton planète) — dédiée,
        distincte du reste du projet, jamais suivie par git."""
        return self.managed_dir / "www-data"

    @property
    def project_root(self) -> Path:
        return CONFIG_PATH.parent

    @property
    def tools_dir(self) -> Path:
        return self.project_root / TOOLS_DIR_NAME

    @property
    def archives_dir(self) -> Path:
        return self.tools_dir / ARCHIVES_DIR_NAME

    @property
    def archives_pending_dir(self) -> Path:
        return self.archives_dir / ARCHIVES_PENDING_SUBDIR

    @property
    def archives_installed_dir(self) -> Path:
        return self.archives_dir / ARCHIVES_INSTALLED_SUBDIR

    @property
    def nexus_links_file(self) -> Path:
        return self.project_root / NEXUS_LINKS_FILE_NAME

    @property
    def tools_md_file(self) -> Path:
        return self.tools_dir / TOOLS_MD_FILE_NAME

    @property
    def inventory_file(self) -> Path:
        return self.managed_dir / "mods_inventory.json"

    @property
    def native_mods_manifest_file(self) -> Path:
        return self.project_root / NATIVE_MODS_MANIFEST_FILE_NAME

    @property
    def native_mods_managed_dir(self) -> Path:
        """Stockage permanent des mods DLL extraits (source des hardlinks
        créés dans bin/ du jeu — doit survivre après l'extraction, contrairement
        à un dossier temporaire)."""
        return self.managed_dir / NATIVE_MODS_MANAGED_SUBDIR

    @property
    def native_mods_deployed_dir(self) -> Path:
        """Dossier réellement chargé par le jeu (bin/NativeMods/, via
        Native Mod Loader) — par opposition à `native_mods_managed_dir`,
        notre copie permanente source des hardlinks."""
        return self.game_bin_dir / NATIVE_MODS_MANAGED_SUBDIR

    @property
    def loose_mods_managed_dir(self) -> Path:
        """Stockage permanent des mods "loose files" (pas de .pak — leurs
        fichiers sont fusionnés ici en préservant la structure Data/, ex:
        Generated/... ou Public/.../Generated/...), source des hardlinks
        créés dans Data/ du jeu — doit survivre après l'extraction."""
        return self.managed_dir / LOOSE_MODS_MANAGED_SUBDIR

    @property
    def profiles_dir(self) -> Path:
        """Profils sauvegardés (copie de modsettings.lsx + manifeste des
        .pak/fichiers loose au moment de la sauvegarde)."""
        return self.managed_dir / PROFILES_MANAGED_SUBDIR

    def has_public_address(self) -> bool:
        return bool(self.public_url and self.public_port)

    def is_complete(self) -> bool:
        return bool(self.bg3_install_dir and self.bg3_appdata_dir)

    def is_valid(self) -> bool:
        if not self.is_complete():
            return False
        return self.install_path.is_dir() and self.appdata_path.is_dir()


def _read_toml_document() -> tomlkit.TOMLDocument:
    """Lit `bg3modtools.toml` en document tomlkit (préserve commentaires et
    mise en forme), ou en crée un vide si absent/invalide."""
    if not CONFIG_PATH.exists():
        return tomlkit.document()
    try:
        return tomlkit.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, tomlkit.exceptions.ParseError):
        return tomlkit.document()


def load_config() -> ModToolsConfig:
    data = _read_toml_document()
    return ModToolsConfig(
        bg3_install_dir=str(data.get("bg3_install_dir", "")),
        bg3_appdata_dir=str(data.get("bg3_appdata_dir", "")),
        active_profile=str(data.get("active_profile", "")),
        public_url=str(data.get("public_url", "")),
        public_port=str(data.get("public_port", "")),
    )


def save_config(config: ModToolsConfig) -> None:
    """Écrit `config` dans `bg3modtools.toml` en ne modifiant que les
    valeurs des clés (via tomlkit) — les commentaires et la mise en forme
    déjà présents dans le fichier ne sont jamais supprimés ni réordonnés."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = _read_toml_document()
    for key, value in asdict(config).items():
        doc[key] = value
    CONFIG_PATH.write_text(tomlkit.dumps(doc), encoding="utf-8")
