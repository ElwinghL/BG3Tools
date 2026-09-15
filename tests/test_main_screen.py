"""Tests pour bg3_mod_tui/screens/main.py — onglets Nexus Mods / mod.io.
NexusClient/ModIOClient/download_file sont entièrement mockés : aucune
requête réseau réelle. Les workers thread (@work(thread=True)) tournent
réellement dans un thread ; les tests attendent leur complétion via des
boucles de pilot.pause()."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

from bg3_mod_tui import screens
from bg3_mod_tui.config import ModToolsConfig
from bg3_mod_tui.providers.modio import ModIOAPIError, ModIOMod
from bg3_mod_tui.providers.nexus import NexusAPIError, NexusMod
from bg3_mod_tui.screens.main import MainScreen


class _MiniApp(App):
    def __init__(self, config: ModToolsConfig) -> None:
        super().__init__()
        self._config = config

    def on_mount(self) -> None:
        self.push_screen(MainScreen(self._config))


async def _wait_until(predicate, *, pilot, attempts=40, interval=0.05):
    for _ in range(attempts):
        await pilot.pause(interval)
        if predicate():
            return True
    return False


def _run(coro):
    asyncio.run(coro)


@pytest.fixture(autouse=True)
def _no_env_leak(monkeypatch):
    for key in (
        "NEXUS_API_KEY",
        "MODIO_API_KEY",
        "MOD_IO_USER_ID",
        "MODIO_API_BASE",
        "MODIO_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_on_mount_loads_both_tabs_successfully(monkeypatch):
    async def scenario():
        nexus_mod = NexusMod(mod_id=1, name="ModA", version="1.0", summary="")
        modio_mod = ModIOMod(mod_id=2, name="ModB", summary="", download_url="http://x/b.zip")

        class FakeNexusClient:
            def __init__(self, api_key):
                pass

            def tracked_mods(self):
                return [nexus_mod]

        class FakeModIOClient:
            def __init__(self, **kwargs):
                pass

            def subscribed_mods(self):
                return [modio_mod]

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)

        app = _MiniApp(ModToolsConfig())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            nexus_table = app.screen.query_one("#nexus-table", DataTable)
            await _wait_until(lambda: nexus_table.row_count == 1, pilot=pilot)
            modio_table = app.screen.query_one("#modio-table", DataTable)
            await _wait_until(lambda: modio_table.row_count == 1, pilot=pilot)

            nexus_status = app.screen.query_one("#nexus-status", Static)
            await _wait_until(lambda: "suivi" in str(nexus_status.render()), pilot=pilot)
            modio_status = app.screen.query_one("#modio-status", Static)
            await _wait_until(lambda: "abonné" in str(modio_status.render()), pilot=pilot)

    _run(scenario())


def test_nexus_load_api_error_shows_message(monkeypatch):
    async def scenario():
        class FakeNexusClient:
            def __init__(self, api_key):
                pass

            def tracked_mods(self):
                raise NexusAPIError("clé invalide")

        class FakeModIOClient:
            def __init__(self, **kwargs):
                pass

            def subscribed_mods(self):
                return []

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)

        app = _MiniApp(ModToolsConfig())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            status = app.screen.query_one("#nexus-status", Static)
            await _wait_until(lambda: "clé invalide" in str(status.render()), pilot=pilot)

    _run(scenario())


def test_nexus_load_unexpected_error_shows_generic_message(monkeypatch):
    async def scenario():
        class FakeNexusClient:
            def __init__(self, api_key):
                raise RuntimeError("boom réseau")

        class FakeModIOClient:
            def __init__(self, **kwargs):
                pass

            def subscribed_mods(self):
                return []

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)

        app = _MiniApp(ModToolsConfig())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            status = app.screen.query_one("#nexus-status", Static)
            await _wait_until(lambda: "Erreur réseau" in str(status.render()), pilot=pilot)

    _run(scenario())


def test_modio_load_api_error_shows_message(monkeypatch):
    async def scenario():
        class FakeNexusClient:
            def __init__(self, api_key):
                pass

            def tracked_mods(self):
                return []

        class FakeModIOClient:
            def __init__(self, **kwargs):
                pass

            def subscribed_mods(self):
                raise ModIOAPIError("clé mod.io invalide")

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)

        app = _MiniApp(ModToolsConfig())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            status = app.screen.query_one("#modio-status", Static)
            await _wait_until(lambda: "clé mod.io invalide" in str(status.render()), pilot=pilot)

    _run(scenario())


def test_modio_load_unexpected_error_shows_generic_message(monkeypatch):
    async def scenario():
        class FakeNexusClient:
            def __init__(self, api_key):
                pass

            def tracked_mods(self):
                return []

        class FakeModIOClient:
            def __init__(self, **kwargs):
                raise RuntimeError("boom")

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)

        app = _MiniApp(ModToolsConfig())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            status = app.screen.query_one("#modio-status", Static)
            await _wait_until(lambda: "Erreur réseau" in str(status.render()), pilot=pilot)

    _run(scenario())


def test_refresh_buttons_and_binding_reload(monkeypatch):
    async def scenario():
        call_counts = {"nexus": 0, "modio": 0}

        class FakeNexusClient:
            def __init__(self, api_key):
                pass

            def tracked_mods(self):
                call_counts["nexus"] += 1
                return []

        class FakeModIOClient:
            def __init__(self, **kwargs):
                pass

            def subscribed_mods(self):
                call_counts["modio"] += 1
                return []

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)

        app = _MiniApp(ModToolsConfig())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            await _wait_until(
                lambda: call_counts["nexus"] >= 1 and call_counts["modio"] >= 1, pilot=pilot
            )

            app.screen.query_one("#nexus-refresh").press()
            app.screen.query_one("#modio-refresh").press()
            await _wait_until(
                lambda: call_counts["nexus"] >= 2 and call_counts["modio"] >= 2, pilot=pilot
            )

            app.screen.action_refresh()
            await _wait_until(
                lambda: call_counts["nexus"] >= 3 and call_counts["modio"] >= 3, pilot=pilot
            )

    _run(scenario())


def test_modio_row_selected_downloads_mod(tmp_path, monkeypatch):
    async def scenario():
        modio_mod = ModIOMod(
            mod_id=42, name="Downloadable", summary="", download_url="http://x/mod.zip"
        )

        class FakeNexusClient:
            def __init__(self, api_key):
                pass

            def tracked_mods(self):
                return []

        class FakeModIOClient:
            def __init__(self, **kwargs):
                pass

            def subscribed_mods(self):
                return [modio_mod]

        downloaded = []

        def fake_download_file(url, target_dir):
            downloaded.append((url, target_dir))
            return target_dir / "mod.zip"

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)
        monkeypatch.setattr(screens.main, "download_file", fake_download_file)

        config = ModToolsConfig(bg3_appdata_dir=str(tmp_path))
        app = _MiniApp(config)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            table = app.screen.query_one("#modio-table", DataTable)
            await _wait_until(lambda: table.row_count == 1, pilot=pilot)

            table.move_cursor(row=0)
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            event = DataTable.RowSelected(table, table.cursor_row, row_key)
            app.screen.handle_modio_row_selected(event)

            await _wait_until(lambda: downloaded, pilot=pilot)
            assert downloaded[0][0] == "http://x/mod.zip"

            status = app.screen.query_one("#modio-status", Static)
            await _wait_until(lambda: "Téléchargé" in str(status.render()), pilot=pilot)

    _run(scenario())


def test_modio_row_selected_no_download_url_is_noop(monkeypatch):
    async def scenario():
        modio_mod = ModIOMod(mod_id=42, name="NoDownload", summary="", download_url=None)

        class FakeNexusClient:
            def __init__(self, api_key):
                pass

            def tracked_mods(self):
                return []

        class FakeModIOClient:
            def __init__(self, **kwargs):
                pass

            def subscribed_mods(self):
                return [modio_mod]

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)

        app = _MiniApp(ModToolsConfig())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            table = app.screen.query_one("#modio-table", DataTable)
            await _wait_until(lambda: table.row_count == 1, pilot=pilot)

            table.move_cursor(row=0)
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            event = DataTable.RowSelected(table, table.cursor_row, row_key)
            # Ne doit pas lever ni démarrer de téléchargement.
            app.screen.handle_modio_row_selected(event)
            await pilot.pause()

    _run(scenario())


def test_modio_download_failure_shows_message(tmp_path, monkeypatch):
    async def scenario():
        modio_mod = ModIOMod(mod_id=1, name="Fails", summary="", download_url="http://x/mod.zip")

        class FakeNexusClient:
            def __init__(self, api_key):
                pass

            def tracked_mods(self):
                return []

        class FakeModIOClient:
            def __init__(self, **kwargs):
                pass

            def subscribed_mods(self):
                return [modio_mod]

        def fake_download_file(url, target_dir):
            raise RuntimeError("disque plein")

        monkeypatch.setattr(screens.main, "NexusClient", FakeNexusClient)
        monkeypatch.setattr(screens.main, "ModIOClient", FakeModIOClient)
        monkeypatch.setattr(screens.main, "download_file", fake_download_file)

        app = _MiniApp(ModToolsConfig())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.download_modio_mod(modio_mod)
            status = app.screen.query_one("#modio-status", Static)
            await _wait_until(
                lambda: "Échec du téléchargement" in str(status.render()), pilot=pilot
            )

    _run(scenario())
