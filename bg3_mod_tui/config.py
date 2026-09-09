"""Configuration persistante du TUI (chemins BG3, dossiers gérés)."""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

import tomli_w

CONFIG_PATH = Path(__file__).resolve().parent.parent / "bg3modtools.toml"
MANAGED_DIR_NAME = "BG3_Managed"

MODS_SUBDIR = "Mods"
PLAYER_PROFILES_MODSETTINGS = Path("PlayerProfiles") / "Public" / "modsettings.lsx"


@dataclass
class ModToolsConfig:
    bg3_install_dir: str = ""
    bg3_appdata_dir: str = ""

    @property
    def install_path(self) -> Path:
        return Path(self.bg3_install_dir)

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
    def managed_modsettings_path(self) -> Path:
        return self.managed_dir / "modsettings.lsx"

    def is_complete(self) -> bool:
        return bool(self.bg3_install_dir and self.bg3_appdata_dir)

    def is_valid(self) -> bool:
        if not self.is_complete():
            return False
        return self.install_path.is_dir() and self.appdata_path.is_dir()


def load_config() -> ModToolsConfig:
    if not CONFIG_PATH.exists():
        return ModToolsConfig()
    try:
        with CONFIG_PATH.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return ModToolsConfig()
    return ModToolsConfig(
        bg3_install_dir=data.get("bg3_install_dir", ""),
        bg3_appdata_dir=data.get("bg3_appdata_dir", ""),
    )


def save_config(config: ModToolsConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("wb") as fh:
        tomli_w.dump(asdict(config), fh)
