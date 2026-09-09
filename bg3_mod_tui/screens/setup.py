"""Assistant de première configuration : emplacements BG3 et mise en place
des liens (Mods/ symlink, modsettings.lsx hardlink)."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static

from bg3_mod_tui.config import ModToolsConfig, save_config
from bg3_mod_tui.linking import LinkingError, setup_links
from bg3_mod_tui.platform_utils import (
    can_create_links_without_admin,
    is_windows,
    relaunch_as_admin,
)
from bg3_mod_tui.screens.directory_picker import DirectoryPickerScreen
from bg3_mod_tui.widgets.path_input import PathInput


class SetupScreen(Screen):
    """Demande l'emplacement d'installation de BG3 puis celui de l'AppData,
    et met en place les liens nécessaires."""

    CSS = """
    SetupScreen {
        align: center middle;
    }
    #setup-box {
        width: 80%;
        max-width: 100;
        border: round $accent;
        padding: 1 2;
    }
    #status {
        margin-top: 1;
        height: auto;
    }
    """

    def __init__(self, config: ModToolsConfig, on_complete) -> None:
        super().__init__()
        self._config = config
        self._on_complete = on_complete

    def compose(self) -> ComposeResult:
        with Vertical(id="setup-box"):
            yield Label("Configuration initiale — BG3 Mod TUI", classes="title")
            yield Label(
                "Renseigne le dossier d'installation du jeu (contenant bin/), "
                "puis le dossier AppData de BG3 (Larian Studios/Baldur's Gate 3, "
                "contenant Mods/ et PlayerProfiles/). Clique sur un champ pour "
                "parcourir les dossiers."
            )
            yield Label("Dossier d'installation de BG3 :")
            yield PathInput(
                value=self._config.bg3_install_dir,
                placeholder=r"ex: C:\...\Steam\steamapps\common\Baldurs Gate 3",
                id="install-dir",
            )
            yield Label("Dossier AppData de BG3 :")
            yield PathInput(
                value=self._config.bg3_appdata_dir,
                placeholder=r"ex: %LOCALAPPDATA%\Larian Studios\Baldur's Gate 3",
                id="appdata-dir",
            )
            yield Label(
                "Adresse publique (optionnel — pour la future fonctionnalité "
                "Web) :"
            )
            yield Input(
                value=self._config.public_url,
                placeholder="ex: https://mon-ddns.exemple.net",
                id="public-url",
            )
            yield Label("Port public (optionnel) :")
            yield Input(
                value=self._config.public_port,
                placeholder="ex: 8080",
                id="public-port",
            )
            yield Button("Valider et configurer les liens", id="submit", variant="primary")
            yield Static(id="status")
        yield Footer()

    @on(PathInput.BrowseRequested)
    def handle_browse_requested(self, event: PathInput.BrowseRequested) -> None:
        target_input = event.path_input

        def on_picked(chosen: str | None) -> None:
            if chosen:
                target_input.value = chosen

        self.app.push_screen(DirectoryPickerScreen(target_input.value), on_picked)

    @on(Button.Pressed, "#submit")
    def handle_submit(self) -> None:
        install_dir = self.query_one("#install-dir", Input).value.strip()
        appdata_dir = self.query_one("#appdata-dir", Input).value.strip()
        status = self.query_one("#status", Static)

        if not install_dir or not appdata_dir:
            status.update("[red]Les deux emplacements sont requis.[/red]")
            return

        install_path = Path(install_dir)
        appdata_path = Path(appdata_dir)
        if not install_path.is_dir():
            status.update(f"[red]Dossier d'installation introuvable : {install_path}[/red]")
            return
        if not appdata_path.is_dir():
            status.update(f"[red]Dossier AppData introuvable : {appdata_path}[/red]")
            return

        self._config.bg3_install_dir = str(install_path)
        self._config.bg3_appdata_dir = str(appdata_path)
        self._config.public_url = self.query_one("#public-url", Input).value.strip()
        self._config.public_port = self.query_one("#public-port", Input).value.strip()

        if is_windows() and not can_create_links_without_admin():
            status.update(
                "[yellow]Privilèges administrateur requis sur Windows pour "
                "créer les liens. Relance en tant qu'administrateur ?[/yellow]"
            )
            self._show_elevate_prompt()
            return

        self._run_linking(status)

    def _show_elevate_prompt(self) -> None:
        box = self.query_one("#setup-box", Vertical)
        if self.query("#elevate-btn"):
            return
        box.mount(
            Button("Relancer en tant qu'administrateur", id="elevate-btn", variant="warning")
        )

    @on(Button.Pressed, "#elevate-btn")
    def handle_elevate(self) -> None:
        status = self.query_one("#status", Static)
        save_config(self._config)
        if relaunch_as_admin():
            self.app.exit()
        else:
            status.update(
                "[red]Impossible de relancer automatiquement. Relance le "
                "programme manuellement via clic droit -> Exécuter en tant "
                "qu'administrateur.[/red]"
            )

    def _run_linking(self, status: Static) -> None:
        try:
            report = setup_links(self._config)
        except LinkingError as exc:
            status.update(f"[red]{exc}[/red]")
            return

        save_config(self._config)
        status.update("[green]Configuration terminée :[/green]\n" + "\n".join(report.steps))
        self.set_timer(1.5, lambda: self._on_complete(self._config))
