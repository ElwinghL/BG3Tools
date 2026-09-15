"""Tests pour bg3_mod_tui.widgets.console_log."""

from __future__ import annotations

import asyncio

from textual import events
from textual.app import App, ComposeResult

from bg3_mod_tui.widgets.console_log import ConsoleLog
from bg3_mod_tui.widgets.context_menu import ContextMenu


class _MiniApp(App):
    def __init__(self):
        super().__init__()
        self.copied: list[str] = []

    def compose(self) -> ComposeResult:
        yield ConsoleLog(id="console")

    def copy_to_clipboard(self, text: str) -> None:
        self.copied.append(text)
        # Ne pas appeler super() : le vrai presse-papiers système n'est pas
        # disponible/pertinent en environnement de test.


def test_write_and_clear() -> None:
    async def run() -> None:
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(ConsoleLog)
            console.write("[red]erreur[/red]")
            console.write("ligne 2")
            await pilot.pause()
            assert console._lines == ["[red]erreur[/red]", "ligne 2"]

            console.clear()
            await pilot.pause()
            assert console._lines == []

    asyncio.run(run())


def test_max_lines_trims_buffer() -> None:
    async def run() -> None:
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(ConsoleLog)
            console._max_lines = 3
            for i in range(5):
                console.write(f"ligne {i}")
            await pilot.pause()
            assert console._lines == ["ligne 2", "ligne 3", "ligne 4"]

    asyncio.run(run())


def test_right_click_opens_context_menu_and_copy() -> None:
    async def run() -> None:
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(ConsoleLog)
            console.write("contenu à copier")
            await pilot.pause()

            console.on_click(events.Click(console, 1, 1, 0, 0, 3, False, False, False, 1, 1))
            await pilot.pause()
            await pilot.pause()
            assert isinstance(app.screen, ContextMenu)

            menu = app.screen
            await pilot.click(menu.query_one("#ctx-copy"))
            await pilot.pause()
            assert app.copied == ["contenu à copier"]

    asyncio.run(run())


def test_left_click_does_not_open_menu() -> None:
    async def run() -> None:
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(ConsoleLog)
            console.on_click(events.Click(console, 1, 1, 0, 0, 1, False, False, False, 1, 1))
            await pilot.pause()
            assert not isinstance(app.screen, ContextMenu)

    asyncio.run(run())


def test_select_all_menu_choice() -> None:
    async def run() -> None:
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(ConsoleLog)
            console._handle_menu_choice("select-all")
            await pilot.pause()  # ne plante pas

    asyncio.run(run())


def test_handle_menu_choice_none_is_noop() -> None:
    async def run() -> None:
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(ConsoleLog)
            console._handle_menu_choice(None)  # ne fait rien, ne plante pas

    asyncio.run(run())
