"""Application Textual principale."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from textual.app import App

from bg3_mod_tui.config import ModToolsConfig, load_config
from bg3_mod_tui.screens.actions import ActionsScreen
from bg3_mod_tui.screens.setup import SetupScreen
from bg3_mod_tui.theme import BG3_THEME

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class BG3ModTUIApp(App):
    """Point d'entrée : lance l'assistant de configuration si nécessaire,
    puis le menu d'actions (téléchargement, nettoyage, extraction, outils)."""

    TITLE = "BG3 Mod TUI"

    def on_mount(self) -> None:
        self.register_theme(BG3_THEME)
        self.theme = BG3_THEME.name

        load_dotenv(ENV_PATH)
        config = load_config()
        if config.is_valid():
            self.push_screen(ActionsScreen(config))
        else:
            self.push_screen(SetupScreen(config, self._go_to_main))

    def _go_to_main(self, config: ModToolsConfig) -> None:
        self.pop_screen()
        self.push_screen(ActionsScreen(config))
