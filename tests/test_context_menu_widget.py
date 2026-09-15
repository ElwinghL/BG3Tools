"""Tests pour bg3_mod_tui.widgets.context_menu (App.run_test/pilot, comme
tests/test_download_console.py)."""

from __future__ import annotations

import asyncio

from textual import events
from textual.app import App, ComposeResult

from bg3_mod_tui.widgets.context_menu import ContextMenu


class _MiniApp(App):
    def __init__(self, items, position):
        super().__init__()
        self._items = items
        self._position = position
        self.result = "not-set"

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(ContextMenu(self._items, self._position), self._set_result)

    def _set_result(self, choice: str | None) -> None:
        self.result = choice


def test_context_menu_choice_dismisses_with_id() -> None:
    async def run() -> None:
        app = _MiniApp([("copy", "Copier"), ("all", "Tout")], (2, 3))
        async with app.run_test(size=(40, 20)) as pilot:
            await pilot.pause()
            menu = app.screen
            assert isinstance(menu, ContextMenu)
            button = menu.query_one("#ctx-copy")
            box = menu.query_one("#context-menu-box")
            assert box.styles.offset.x.value == 2
            assert box.styles.offset.y.value == 3
            await pilot.click(button)
            await pilot.pause()
            assert app.result == "copy"

    asyncio.run(run())


def test_context_menu_escape_dismisses_with_none() -> None:
    async def run() -> None:
        app = _MiniApp([("copy", "Copier")], (0, 0))
        async with app.run_test(size=(40, 20)) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.result is None

    asyncio.run(run())


def test_context_menu_click_outside_dismisses_with_none() -> None:
    async def run() -> None:
        app = _MiniApp([("copy", "Copier")], (0, 0))
        async with app.run_test(size=(40, 20)) as pilot:
            await pilot.pause()
            menu = app.screen
            menu.on_click(events.Click(menu, 0, 0, 0, 0, 0, False, False, False, 1, None))
            await pilot.pause()
            assert app.result is None

    asyncio.run(run())
