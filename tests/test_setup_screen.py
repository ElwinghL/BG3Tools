"""Tests pour bg3_mod_tui/screens/setup.py — assistant de première
configuration. setup_links/save_config/relaunch_as_admin sont mockés
(aucun vrai lien/registre créé) ; les dossiers d'installation/AppData
existent réellement sous tmp_path pour passer les vérifications
`is_dir()`."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Button, Input, Static

from bg3_mod_tui import screens
from bg3_mod_tui.config import ModToolsConfig
from bg3_mod_tui.linking import LinkingError, LinkingReport
from bg3_mod_tui.screens.setup import SetupScreen
from bg3_mod_tui.widgets.path_input import PathInput


class _MiniApp(App):
    def __init__(self, config: ModToolsConfig, on_complete) -> None:
        super().__init__()
        self._config = config
        self._on_complete = on_complete

    def on_mount(self) -> None:
        self.push_screen(SetupScreen(self._config, self._on_complete))


def _run(coro):
    asyncio.run(coro)


def test_submit_missing_dirs_shows_error():
    async def scenario():
        config = ModToolsConfig()
        completed = []
        app = _MiniApp(config, completed.append)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()
            status = app.screen.query_one("#status", Static)
            assert "requis" in str(status.render())
            assert completed == []

    _run(scenario())


def test_submit_nonexistent_install_dir_shows_error(tmp_path):
    async def scenario():
        appdata = tmp_path / "AppData"
        appdata.mkdir()
        config = ModToolsConfig()
        app = _MiniApp(config, lambda cfg: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#install-dir", Input).value = str(tmp_path / "missing_install")
            app.screen.query_one("#appdata-dir", Input).value = str(appdata)
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()
            status = app.screen.query_one("#status", Static)
            assert "introuvable" in str(status.render())

    _run(scenario())


def test_submit_nonexistent_appdata_dir_shows_error(tmp_path):
    async def scenario():
        install = tmp_path / "Install"
        install.mkdir()
        config = ModToolsConfig()
        app = _MiniApp(config, lambda cfg: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#install-dir", Input).value = str(install)
            app.screen.query_one("#appdata-dir", Input).value = str(tmp_path / "missing_appdata")
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()
            status = app.screen.query_one("#status", Static)
            assert "AppData introuvable" in str(status.render())

    _run(scenario())


def test_submit_success_runs_linking_and_completes(tmp_path, monkeypatch):
    async def scenario():
        install = tmp_path / "Install"
        install.mkdir()
        appdata = tmp_path / "AppData"
        appdata.mkdir()
        config = ModToolsConfig()

        monkeypatch.setattr(screens.setup, "is_windows", lambda: False)
        monkeypatch.setattr(screens.setup, "save_config", lambda cfg: None)
        monkeypatch.setattr(
            screens.setup, "setup_links", lambda cfg: LinkingReport(steps=["étape 1", "étape 2"])
        )

        completed = []
        app = _MiniApp(config, completed.append)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#install-dir", Input).value = str(install)
            app.screen.query_one("#appdata-dir", Input).value = str(appdata)
            app.screen.query_one("#public-url", Input).value = "https://example.test"
            app.screen.query_one("#public-port", Input).value = "8080"
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()

            status = app.screen.query_one("#status", Static)
            assert "terminée" in str(status.render())
            assert config.bg3_install_dir == str(install)
            assert config.bg3_appdata_dir == str(appdata)
            assert config.public_url == "https://example.test"
            assert config.public_port == "8080"

            # Le timer de complétion (1.5s) : on force son déclenchement.
            await pilot.pause(1.6)
            assert completed == [config]

    _run(scenario())


def test_submit_linking_error_shows_message(tmp_path, monkeypatch):
    async def scenario():
        install = tmp_path / "Install"
        install.mkdir()
        appdata = tmp_path / "AppData"
        appdata.mkdir()
        config = ModToolsConfig()

        monkeypatch.setattr(screens.setup, "is_windows", lambda: False)

        def fake_setup_links(cfg):
            raise LinkingError("échec de liaison")

        monkeypatch.setattr(screens.setup, "setup_links", fake_setup_links)

        app = _MiniApp(config, lambda cfg: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#install-dir", Input).value = str(install)
            app.screen.query_one("#appdata-dir", Input).value = str(appdata)
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()

            status = app.screen.query_one("#status", Static)
            assert "échec de liaison" in str(status.render())

    _run(scenario())


def test_submit_windows_requires_admin_shows_elevate_button(tmp_path, monkeypatch):
    async def scenario():
        install = tmp_path / "Install"
        install.mkdir()
        appdata = tmp_path / "AppData"
        appdata.mkdir()
        config = ModToolsConfig()

        monkeypatch.setattr(screens.setup, "is_windows", lambda: True)
        monkeypatch.setattr(screens.setup, "can_create_links_without_admin", lambda: False)

        app = _MiniApp(config, lambda cfg: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#install-dir", Input).value = str(install)
            app.screen.query_one("#appdata-dir", Input).value = str(appdata)
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()

            status = app.screen.query_one("#status", Static)
            assert "administrateur" in str(status.render())
            elevate_button = app.screen.query_one("#elevate-btn", Button)
            assert elevate_button is not None

            # Un deuxième clic sur "submit" ne doit pas monter un deuxième
            # bouton élévation (garde-fou _show_elevate_prompt).
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()
            assert len(app.screen.query("#elevate-btn")) == 1

    _run(scenario())


def test_elevate_button_success_exits_app(tmp_path, monkeypatch):
    async def scenario():
        install = tmp_path / "Install"
        install.mkdir()
        appdata = tmp_path / "AppData"
        appdata.mkdir()
        config = ModToolsConfig()

        monkeypatch.setattr(screens.setup, "is_windows", lambda: True)
        monkeypatch.setattr(screens.setup, "can_create_links_without_admin", lambda: False)
        monkeypatch.setattr(screens.setup, "save_config", lambda cfg: None)
        monkeypatch.setattr(screens.setup, "relaunch_as_admin", lambda: True)

        app = _MiniApp(config, lambda cfg: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#install-dir", Input).value = str(install)
            app.screen.query_one("#appdata-dir", Input).value = str(appdata)
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()
            app.screen.query_one("#elevate-btn", Button).press()
            await pilot.pause()
            assert app._exit is True

    _run(scenario())


def test_elevate_button_failure_shows_message(tmp_path, monkeypatch):
    async def scenario():
        install = tmp_path / "Install"
        install.mkdir()
        appdata = tmp_path / "AppData"
        appdata.mkdir()
        config = ModToolsConfig()

        monkeypatch.setattr(screens.setup, "is_windows", lambda: True)
        monkeypatch.setattr(screens.setup, "can_create_links_without_admin", lambda: False)
        monkeypatch.setattr(screens.setup, "save_config", lambda cfg: None)
        monkeypatch.setattr(screens.setup, "relaunch_as_admin", lambda: False)

        app = _MiniApp(config, lambda cfg: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one("#install-dir", Input).value = str(install)
            app.screen.query_one("#appdata-dir", Input).value = str(appdata)
            app.screen.query_one("#submit", Button).press()
            await pilot.pause()
            app.screen.query_one("#elevate-btn", Button).press()
            await pilot.pause()
            status = app.screen.query_one("#status", Static)
            assert "Impossible de relancer" in str(status.render())

    _run(scenario())


def test_browse_requested_opens_picker_and_fills_input(tmp_path):
    async def scenario():
        chosen_dir = tmp_path / "Chosen"
        chosen_dir.mkdir()
        config = ModToolsConfig()
        app = _MiniApp(config, lambda cfg: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            input_widget = app.screen.query_one("#install-dir", PathInput)
            app.screen.handle_browse_requested(PathInput.BrowseRequested(input_widget))
            await pilot.pause()
            # Le sélecteur de dossier est bien poussé par-dessus.
            from bg3_mod_tui.screens.directory_picker import DirectoryPickerScreen

            assert isinstance(app.screen, DirectoryPickerScreen)
            app.screen.dismiss(str(chosen_dir))
            await pilot.pause()
            assert input_widget.value == str(chosen_dir)

    _run(scenario())


def test_browse_requested_cancelled_leaves_input_unchanged(tmp_path):
    async def scenario():
        config = ModToolsConfig()
        app = _MiniApp(config, lambda cfg: None)
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            input_widget = app.screen.query_one("#install-dir", PathInput)
            original_value = input_widget.value
            app.screen.handle_browse_requested(PathInput.BrowseRequested(input_widget))
            await pilot.pause()
            app.screen.dismiss(None)
            await pilot.pause()
            assert input_widget.value == original_value

    _run(scenario())
