"""Écran principal : menu d'actions (téléchargement, nettoyage, extraction,
outils) plutôt qu'une liste de mods à parcourir."""

from __future__ import annotations

import os
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Label, ListItem, ListView, Static

from bg3_mod_tui.config import ModToolsConfig
from bg3_mod_tui.game_deploy import deploy_native_mod_loader, deploy_script_extender
from bg3_mod_tui.launcher import LauncherError, launch_tool, open_protontricks
from bg3_mod_tui.linking import LinkingError, setup_links
from bg3_mod_tui.platform_utils import is_windows
from bg3_mod_tui.mod_pipeline import (
    clean_pak_files,
    download_mods_from_links_file,
    download_subscribed_modio_mods,
    extract_archives_to_mods,
)
from bg3_mod_tui.providers.modio import ModIOAPIError, ModIOClient
from bg3_mod_tui.providers.nexus import NexusAPIError, NexusClient
from bg3_mod_tui.tools_manager import ToolsError, download_and_extract_tool, find_executables, parse_tools_table
from bg3_mod_tui.widgets.console_log import ConsoleLog


TOOL_ICON = "🛠"


class _ToolListItem(ListItem):
    """Élément de liste représentant un exécutable : mémorise son chemin
    complet (utilisé pour le lancement) tout en n'affichant que son nom."""

    def __init__(self, exe_path: Path) -> None:
        self.exe_path = exe_path
        super().__init__(Label(f"{TOOL_ICON} {exe_path.name}"))


class ToolPickerScreen(ModalScreen[Path | None]):
    """Liste les exécutables trouvés sous Tools/, groupés par dossier
    d'outil, pour en choisir un à lancer (clic simple, ou sélection au
    clavier + bouton « Lancer »)."""

    CSS = """
    ToolPickerScreen {
        align: center middle;
    }
    #tool-picker-box {
        width: 80%;
        max-width: 100;
        height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #tool-groups {
        height: 1fr;
    }
    .tool-group-header {
        margin-top: 1;
        text-style: bold;
        color: $accent;
    }
    ListView {
        height: auto;
        background: transparent;
    }
    ListView > ListItem {
        margin-bottom: 1;
        padding: 0 1;
    }
    #tool-picker-buttons {
        height: auto;
        margin-top: 1;
    }
    #tool-picker-buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, executables: list[Path], project_root: Path) -> None:
        super().__init__()
        self._executables = executables
        self._project_root = project_root
        self._selected_exe: Path | None = executables[0] if executables else None

    def _group_label(self, exe: Path) -> str:
        try:
            relative = exe.relative_to(self._project_root)
        except ValueError:
            return str(exe.parent)
        parts = relative.parts
        # Le premier segment sous Tools/ identifie l'outil (ex: "Tools",
        # "BG3-Load-Order-Optimizer", ...) — on regroupe par ce dossier.
        return parts[1] if len(parts) > 1 else parts[0]

    def compose(self) -> ComposeResult:
        with Vertical(id="tool-picker-box"):
            yield Label("Choisir un outil à lancer", classes="title")
            groups: dict[str, list[Path]] = {}
            for exe in self._executables:
                groups.setdefault(self._group_label(exe), []).append(exe)

            with VerticalScroll(id="tool-groups"):
                for group_name in sorted(groups):
                    yield Label(group_name, classes="tool-group-header")
                    yield ListView(
                        *[_ToolListItem(exe) for exe in sorted(groups[group_name])]
                    )

            with Horizontal(id="tool-picker-buttons"):
                yield Button("Lancer", id="tool-picker-launch", variant="primary")
                yield Button("Annuler", id="tool-picker-cancel")

    @on(ListView.Highlighted)
    def handle_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, _ToolListItem):
            self._selected_exe = event.item.exe_path

    @on(ListView.Selected)
    def handle_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _ToolListItem):
            self.dismiss(event.item.exe_path)

    @on(Button.Pressed, "#tool-picker-launch")
    def handle_launch(self) -> None:
        self.dismiss(self._selected_exe)

    @on(Button.Pressed, "#tool-picker-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)


class ActionsScreen(Screen):
    """Menu d'actions pour préparer/installer les mods BG3."""

    CSS = """
    #actions-menu {
        width: 40;
        border: round $accent;
        padding: 1 2;
    }
    #actions-menu Button {
        width: 100%;
        margin-bottom: 1;
    }
    #logs-panel {
        margin-left: 2;
        width: 1fr;
    }
    #actions-log-label {
        height: auto;
    }
    #actions-log {
        border: round $panel;
        height: 1fr;
    }
    #tools-log-label {
        margin-top: 1;
        height: auto;
    }
    #tools-log {
        border: round $accent;
        height: 10;
    }
    #actions-body {
        height: 1fr;
    }
    #menu-spacer {
        height: 1fr;
    }
    #action-quit {
        width: 100%;
    }
    """

    BINDINGS = [("q", "quit_app", "Quitter")]

    def __init__(self, config: ModToolsConfig) -> None:
        super().__init__()
        self._config = config

    def compose(self) -> ComposeResult:
        with Horizontal(id="actions-body"):
            with Vertical(id="actions-menu"):
                yield Label("BG3 Mod Tools", classes="title")
                yield Button("1. Télécharger les mods (Nexus)", id="action-download-mods")
                yield Button("2. Récupérer les mods (mod.io)", id="action-download-modio")
                yield Button("3. Nettoyer les .pak de Mods/", id="action-clean-paks")
                yield Button("4. Synchroniser modsettings.lsx", id="action-sync-modsettings")
                yield Button("5. Extraire les archives vers Mods/", id="action-extract")
                yield Button("6. Télécharger/MAJ les outils (TOOLS.md)", id="action-tools")
                yield Button("7. Lancer un outil...", id="action-launch-tool")
                if not is_windows():
                    yield Button("8. Ouvrir protontricks (préfixe BG3)", id="action-protontricks")
                yield Static(id="menu-spacer")
                yield Button("Quitter", id="action-quit", variant="error")
            with Vertical(id="logs-panel"):
                yield Label("Console tâches", id="actions-log-label")
                yield ConsoleLog(id="actions-log", wrap=True, highlight=True, markup=True)
                yield Label("Console outils", id="tools-log-label")
                yield ConsoleLog(id="tools-log", wrap=True, highlight=True, markup=True)
        yield Footer()

    def _log(self, message: str) -> None:
        self.query_one("#actions-log", ConsoleLog).write(message)

    def _tool_log(self, message: str) -> None:
        self.query_one("#tools-log", ConsoleLog).write(message)

    @on(Button.Pressed, "#action-download-mods")
    def handle_download_mods(self) -> None:
        self.run_download_mods()

    @work(exclusive=True, thread=True)
    def run_download_mods(self) -> None:
        log = lambda msg: self.app.call_from_thread(self._log, msg)
        log("=== Téléchargement des mods listés dans nexus_links_to_add.md ===")
        api_key = os.environ.get("NEXUS_API_KEY", "")
        try:
            client = NexusClient(api_key)
            report = download_mods_from_links_file(
                client, self._config.nexus_links_file, self._config.archives_dir, log=log
            )
            log(
                f"Terminé : {len(report['downloaded'])} téléchargé(s), "
                f"{len(report['skipped'])} déjà présent(s), "
                f"{len(report['failed'])} échec(s)."
            )
        except NexusAPIError as exc:
            log(f"[red]Erreur : {exc}[/red]")
        except Exception as exc:
            log(f"[red]Erreur inattendue : {exc}[/red]")

    @on(Button.Pressed, "#action-download-modio")
    def handle_download_modio(self) -> None:
        self.run_download_modio()

    @work(exclusive=True, thread=True)
    def run_download_modio(self) -> None:
        log = lambda msg: self.app.call_from_thread(self._log, msg)
        log("=== Récupération des mods abonnés sur mod.io ===")
        try:
            client = ModIOClient(
                api_key=os.environ.get("MODIO_API_KEY", ""),
                user_id=os.environ.get("MOD_IO_USER_ID") or None,
                api_base=os.environ.get("MODIO_API_BASE") or None,
                access_token=os.environ.get("MODIO_ACCESS_TOKEN") or None,
            )
            report = download_subscribed_modio_mods(client, self._config.archives_dir, log=log)
            log(
                f"Terminé : {len(report['downloaded'])} téléchargé(s), "
                f"{len(report['skipped'])} déjà présent(s), "
                f"{len(report['failed'])} échec(s)."
            )
        except ModIOAPIError as exc:
            log(f"[red]Erreur : {exc}[/red]")
        except Exception as exc:
            log(f"[red]Erreur inattendue : {exc}[/red]")

    @on(Button.Pressed, "#action-clean-paks")
    def handle_clean_paks(self) -> None:
        self.run_clean_paks()

    @work(exclusive=True, thread=True)
    def run_clean_paks(self) -> None:
        log = lambda msg: self.app.call_from_thread(self._log, msg)
        log("=== Nettoyage des .pak de Mods/ ===")
        clean_pak_files(self._config.managed_mods_link, log=log)

    @on(Button.Pressed, "#action-sync-modsettings")
    def handle_sync_modsettings(self) -> None:
        self.run_sync_modsettings()

    @work(exclusive=True, thread=True)
    def run_sync_modsettings(self) -> None:
        log = lambda msg: self.app.call_from_thread(self._log, msg)
        log("=== Synchronisation de modsettings.lsx ===")
        try:
            report = setup_links(self._config)
            for step in report.steps:
                log(step)
        except LinkingError as exc:
            log(f"[red]Erreur : {exc}[/red]")

    @on(Button.Pressed, "#action-extract")
    def handle_extract(self) -> None:
        self.run_extract()

    @work(exclusive=True, thread=True)
    def run_extract(self) -> None:
        log = lambda msg: self.app.call_from_thread(self._log, msg)
        log("=== Extraction des archives vers Mods/ ===")
        report = extract_archives_to_mods(
            self._config.archives_dir,
            self._config.managed_mods_link,
            self._config.archives_pending_dir,
            self._config.archives_installed_dir,
            log=log,
        )
        log(
            f"Terminé : {len(report['installed'])} installée(s), "
            f"{len(report['pending'])} à traiter manuellement, "
            f"{len(report['failed'])} échec(s)."
        )

    @on(Button.Pressed, "#action-tools")
    def handle_tools(self) -> None:
        self.run_download_tools()

    @work(exclusive=True, thread=True)
    def run_download_tools(self) -> None:
        log = lambda msg: self.app.call_from_thread(self._log, msg)
        log("=== Téléchargement/mise à jour des outils (TOOLS.md) ===")
        try:
            entries = parse_tools_table(self._config.tools_md_file)
        except ToolsError as exc:
            log(f"[red]Erreur : {exc}[/red]")
            return
        for entry in entries:
            download_and_extract_tool(entry, self._config.project_root, log=log)

        log("--- Déploiement des DLL dans le jeu (bin/) ---")
        deploy_native_mod_loader(self._config.tools_dir, self._config.game_bin_dir, log=log)
        deploy_script_extender(self._config.tools_dir, self._config.game_bin_dir, log=log)
        log("Terminé.")

    @on(Button.Pressed, "#action-launch-tool")
    def handle_launch_tool(self) -> None:
        executables = find_executables(self._config.tools_dir)
        if not executables:
            self._tool_log("[yellow]Aucun exécutable trouvé sous Tools/.[/yellow]")
            return

        def on_picked(exe_path: Path | None) -> None:
            if exe_path is None:
                return
            self.run_launch_tool(exe_path)

        self.app.push_screen(ToolPickerScreen(executables, self._config.project_root), on_picked)

    @work(exclusive=False, thread=True)
    def run_launch_tool(self, exe_path: Path) -> None:
        log = lambda msg: self.app.call_from_thread(self._tool_log, msg)
        log_dir = self._config.logs_dir
        try:
            launch_tool(exe_path, reference_path=self._config.appdata_path, log_dir=log_dir)
            log(f"Lancé : {exe_path.name} (sortie journalisée dans {log_dir / (exe_path.stem + '.log')})")
        except LauncherError as exc:
            log(f"[red]Erreur : {exc}[/red]")

    @on(Button.Pressed, "#action-protontricks")
    def handle_protontricks(self) -> None:
        self.run_protontricks()

    @work(exclusive=False, thread=True)
    def run_protontricks(self) -> None:
        log = lambda msg: self.app.call_from_thread(self._tool_log, msg)
        log_dir = self._config.logs_dir
        try:
            open_protontricks(self._config.appdata_path, log_dir=log_dir)
            log(f"protontricks ouvert (préfixe BG3, sortie journalisée dans {log_dir / 'protontricks.log'}).")
        except LauncherError as exc:
            log(f"[red]Erreur : {exc}[/red]")

    @on(Button.Pressed, "#action-quit")
    def handle_quit(self) -> None:
        self.app.exit()

    def action_quit_app(self) -> None:
        self.app.exit()
