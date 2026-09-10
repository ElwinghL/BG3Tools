"""Application Textual principale."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from textual.app import App
from textual.binding import Binding

from bg3_mod_tui.config import ModToolsConfig, load_config
from bg3_mod_tui.crash_log import log_crash
from bg3_mod_tui.screens.actions import ActionsScreen
from bg3_mod_tui.screens.setup import SetupScreen
from bg3_mod_tui.theme import BG3_THEME

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


class BG3ModTUIApp(App):
    """Point d'entrée : lance l'assistant de configuration si nécessaire,
    puis le menu d'actions (téléchargement, nettoyage, extraction, outils)."""

    TITLE = "BG3 Mod TUI"

    BINDINGS = [
        # Textual fournit nativement `ctrl+c`/`super+c` pour copier la
        # sélection de texte (Screen.action_copy_text), mais dans un
        # terminal, Ctrl+C est habituellement intercepté comme signal
        # d'interruption avant même d'atteindre l'application (ou en tout
        # cas ne correspond pas au réflexe habituel de copie en usage
        # terminal). La convention "copier la sélection" y est plutôt
        # Ctrl+Maj+C : on ajoute donc ce raccourci en plus, sans toucher au
        # binding natif, en réutilisant la même action que lui
        # (`screen.copy_text`) pour copier la sélection (console de logs
        # comprise) dans le presse-papiers.
        Binding("ctrl+shift+c", "screen.copy_text", "Copier la sélection", show=False),
    ]

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

    def _handle_exception(self, error: Exception) -> None:
        # Le TUI tourne dans une fenêtre de terminal dédiée qui se referme
        # trop vite pour lire une trace à l'écran : voir `bg3_mod_tui.crash_log`.
        log_crash(error)
        super()._handle_exception(error)
