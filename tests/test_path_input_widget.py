"""Tests pour bg3_mod_tui/widgets/path_input.py — champ de saisie de
chemin déclenchant l'ouverture du sélecteur de dossier au clic."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from bg3_mod_tui.widgets.path_input import PathInput


class _MiniApp(App):
    def compose(self) -> ComposeResult:
        yield PathInput(id="path-input")


def test_click_posts_browse_requested():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            input_widget = app.query_one("#path-input", PathInput)

            captured = []
            original_post_message = input_widget.post_message
            input_widget.post_message = lambda message: (
                captured.append(message),
                original_post_message(message),
            )[1]

            await pilot.click("#path-input")
            await pilot.pause()

            browse_events = [m for m in captured if isinstance(m, PathInput.BrowseRequested)]
            assert len(browse_events) == 1
            assert browse_events[0].control is input_widget

    asyncio.run(scenario())


def test_browse_requested_control_property():
    input_widget = PathInput()
    message = PathInput.BrowseRequested(input_widget)
    assert message.control is input_widget
