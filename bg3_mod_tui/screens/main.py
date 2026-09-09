"""Écran principal : navigation des mods suivis/abonnés sur Nexus Mods et
mod.io, et téléchargement vers le dossier Mods géré."""

from __future__ import annotations

import os

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static, TabbedContent, TabPane

from bg3_mod_tui.config import ModToolsConfig
from bg3_mod_tui.downloader import download_file
from bg3_mod_tui.providers.modio import ModIOAPIError, ModIOClient, ModIOMod
from bg3_mod_tui.providers.nexus import NexusAPIError, NexusClient, NexusMod


class MainScreen(Screen):
    """Onglets Nexus Mods / mod.io listant les mods suivis/abonnés."""

    CSS = """
    #nexus-status, #modio-status {
        height: auto;
        margin: 1 0;
    }
    """

    BINDINGS = [("r", "refresh", "Rafraîchir")]

    def __init__(self, config: ModToolsConfig) -> None:
        super().__init__()
        self._config = config
        self._nexus_mods: list[NexusMod] = []
        self._modio_mods: list[ModIOMod] = []

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("Nexus Mods", id="tab-nexus"):
                with Vertical():
                    yield Static(
                        "Mods suivis (tracked) sur Nexus Mods pour Baldur's Gate 3.",
                        id="nexus-status",
                    )
                    yield DataTable(id="nexus-table")
                    yield Button("Rafraîchir", id="nexus-refresh")
            with TabPane("mod.io", id="tab-modio"):
                with Vertical():
                    yield Static("Mods auxquels le compte mod.io est abonné.", id="modio-status")
                    yield DataTable(id="modio-table")
                    yield Button("Rafraîchir", id="modio-refresh")
        yield Footer()

    def on_mount(self) -> None:
        nexus_table = self.query_one("#nexus-table", DataTable)
        nexus_table.add_columns("ID", "Nom", "Version")
        nexus_table.cursor_type = "row"

        modio_table = self.query_one("#modio-table", DataTable)
        modio_table.add_columns("ID", "Nom", "Téléchargeable")
        modio_table.cursor_type = "row"

        self.load_nexus_mods()
        self.load_modio_mods()

    @on(Button.Pressed, "#nexus-refresh")
    def handle_nexus_refresh(self) -> None:
        self.load_nexus_mods()

    @on(Button.Pressed, "#modio-refresh")
    def handle_modio_refresh(self) -> None:
        self.load_modio_mods()

    def action_refresh(self) -> None:
        self.load_nexus_mods()
        self.load_modio_mods()

    @work(exclusive=True, thread=True)
    def load_nexus_mods(self) -> None:
        status = self.query_one("#nexus-status", Static)
        self.app.call_from_thread(status.update, "Chargement des mods Nexus...")
        api_key = os.environ.get("NEXUS_API_KEY", "")
        try:
            client = NexusClient(api_key)
            mods = client.tracked_mods()
        except NexusAPIError as exc:
            self.app.call_from_thread(status.update, f"[#C46F6F]{exc}[/#C46F6F]")
            return
        except Exception as exc:  # erreurs réseau, etc.
            self.app.call_from_thread(status.update, f"[#C46F6F]Erreur réseau : {exc}[/#C46F6F]")
            return

        self._nexus_mods = mods
        self.app.call_from_thread(self._populate_nexus_table)
        self.app.call_from_thread(status.update, f"{len(mods)} mod(s) suivi(s).")

    def _populate_nexus_table(self) -> None:
        table = self.query_one("#nexus-table", DataTable)
        table.clear()
        for mod in self._nexus_mods:
            table.add_row(str(mod.mod_id), mod.name, mod.version, key=str(mod.mod_id))

    @work(exclusive=True, thread=True)
    def load_modio_mods(self) -> None:
        status = self.query_one("#modio-status", Static)
        self.app.call_from_thread(status.update, "Chargement des mods mod.io...")
        try:
            client = ModIOClient(
                api_key=os.environ.get("MODIO_API_KEY", ""),
                user_id=os.environ.get("MOD_IO_USER_ID") or None,
                api_base=os.environ.get("MODIO_API_BASE") or None,
                access_token=os.environ.get("MODIO_ACCESS_TOKEN") or None,
            )
            mods = client.subscribed_mods()
        except ModIOAPIError as exc:
            self.app.call_from_thread(status.update, f"[#C46F6F]{exc}[/#C46F6F]")
            return
        except Exception as exc:
            self.app.call_from_thread(status.update, f"[#C46F6F]Erreur réseau : {exc}[/#C46F6F]")
            return

        self._modio_mods = mods
        self.app.call_from_thread(self._populate_modio_table)
        self.app.call_from_thread(status.update, f"{len(mods)} mod(s) abonné(s).")

    def _populate_modio_table(self) -> None:
        table = self.query_one("#modio-table", DataTable)
        table.clear()
        for mod in self._modio_mods:
            table.add_row(
                str(mod.mod_id),
                mod.name,
                "oui" if mod.download_url else "non",
                key=str(mod.mod_id),
            )

    @on(DataTable.RowSelected, "#modio-table")
    def handle_modio_row_selected(self, event: DataTable.RowSelected) -> None:
        mod = next((m for m in self._modio_mods if str(m.mod_id) == str(event.row_key.value)), None)
        if mod is None or not mod.download_url:
            return
        self.download_modio_mod(mod)

    @work(exclusive=False, thread=True)
    def download_modio_mod(self, mod: ModIOMod) -> None:
        status = self.query_one("#modio-status", Static)
        self.app.call_from_thread(status.update, f"Téléchargement de {mod.name}...")
        try:
            target_dir = self._config.managed_mods_link
            path = download_file(mod.download_url, target_dir)
        except Exception as exc:
            self.app.call_from_thread(status.update, f"[#C46F6F]Échec du téléchargement : {exc}[/#C46F6F]")
            return
        self.app.call_from_thread(status.update, f"[#89A8B1]Téléchargé : {path}[/#89A8B1]")
