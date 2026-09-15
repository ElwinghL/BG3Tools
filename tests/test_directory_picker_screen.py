"""Tests pour bg3_mod_tui/screens/directory_picker.py — sélecteur de
dossier modal. Monté dans une App Textual minimale ; aucune vraie
sélection de fichier système, tout se fait sous tmp_path."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import DirectoryTree, Input, Label

from bg3_mod_tui.screens.directory_picker import DirectoryPickerScreen, VisibleDirectoryTree


class _MiniApp(App):
    def __init__(self, initial_path: str = "") -> None:
        super().__init__()
        self._initial_path = initial_path

    def compose(self) -> ComposeResult:
        yield Label("host")

    def open_picker(self, on_dismiss) -> None:
        self.push_screen(DirectoryPickerScreen(self._initial_path), on_dismiss)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# VisibleDirectoryTree.filter_paths
# ---------------------------------------------------------------------------


def test_visible_directory_tree_filters_hidden(tmp_path):
    visible = tmp_path / "visible"
    hidden = tmp_path / ".hidden"
    visible.mkdir()
    hidden.mkdir()
    tree = VisibleDirectoryTree(str(tmp_path))
    filtered = list(tree.filter_paths([visible, hidden]))
    assert filtered == [visible]


# ---------------------------------------------------------------------------
# _compute_root
# ---------------------------------------------------------------------------


def test_compute_root_empty_string_returns_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert DirectoryPickerScreen._compute_root("") == tmp_path


def test_compute_root_valid_dir(tmp_path):
    d = tmp_path / "sub"
    d.mkdir()
    assert DirectoryPickerScreen._compute_root(str(d)) == d


def test_compute_root_file_path_uses_parent(tmp_path):
    f = tmp_path / "file.txt"
    f.write_bytes(b"")
    assert DirectoryPickerScreen._compute_root(str(f)) == tmp_path


def test_compute_root_nonexistent_falls_back_to_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = DirectoryPickerScreen._compute_root(str(tmp_path / "missing" / "deep" / "path"))
    assert result == tmp_path


def test_compute_root_home_missing_uses_anchor(monkeypatch, tmp_path):
    fake_home = tmp_path / "no_such_home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    result = DirectoryPickerScreen._compute_root("/nonexistent/deep/path")
    assert result == Path("/")


# ---------------------------------------------------------------------------
# Comportement modal
# ---------------------------------------------------------------------------


def test_choose_dismisses_with_selected_path(tmp_path):
    async def scenario():
        app = _MiniApp(str(tmp_path))
        async with app.run_test(size=(100, 40)) as pilot:
            results = []
            app.open_picker(results.append)
            await pilot.pause()
            button = app.screen.query_one("#picker-choose")
            button.press()
            await pilot.pause()
            assert results == [str(tmp_path)]

    _run(scenario())


def test_cancel_button_dismisses_with_none(tmp_path):
    async def scenario():
        app = _MiniApp(str(tmp_path))
        async with app.run_test(size=(100, 40)) as pilot:
            results = []
            app.open_picker(results.append)
            await pilot.pause()
            button = app.screen.query_one("#picker-cancel")
            button.press()
            await pilot.pause()
            assert results == [None]

    _run(scenario())


def test_escape_action_dismisses_with_none(tmp_path):
    async def scenario():
        app = _MiniApp(str(tmp_path))
        async with app.run_test(size=(100, 40)) as pilot:
            results = []
            app.open_picker(results.append)
            await pilot.pause()
            screen = app.screen
            screen.action_cancel()
            await pilot.pause()
            assert results == [None]

    _run(scenario())


def test_directory_selected_updates_selection_label(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()

    async def scenario():
        app = _MiniApp(str(tmp_path))
        async with app.run_test(size=(100, 40)) as pilot:
            results = []
            app.open_picker(results.append)
            await pilot.pause()
            screen = app.screen
            screen.handle_directory_selected(
                DirectoryTree.DirectorySelected(app.screen.query_one(VisibleDirectoryTree), sub)
            )
            await pilot.pause()
            label = app.screen.query_one("#picker-current", Label)
            assert str(sub) in str(label.content)
            screen.action_cancel()
            await pilot.pause()

    _run(scenario())


def test_goto_manual_path_valid_dir(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()

    async def scenario():
        app = _MiniApp(str(tmp_path))
        async with app.run_test(size=(100, 40)) as pilot:
            results = []
            app.open_picker(results.append)
            await pilot.pause()
            input_widget = app.screen.query_one("#picker-manual-path", Input)
            input_widget.value = str(sub)
            goto_button = app.screen.query_one("#picker-goto")
            goto_button.press()
            await pilot.pause()

            label = app.screen.query_one("#picker-current", Label)
            assert str(sub) in str(label.content)
            tree = app.screen.query_one("#picker-tree", VisibleDirectoryTree)
            assert Path(tree.path) == sub

            app.screen.query_one("#picker-cancel").press()
            await pilot.pause()

    _run(scenario())


def test_goto_manual_path_invalid_dir_shows_error(tmp_path):
    async def scenario():
        app = _MiniApp(str(tmp_path))
        async with app.run_test(size=(100, 40)) as pilot:
            results = []
            app.open_picker(results.append)
            await pilot.pause()
            input_widget = app.screen.query_one("#picker-manual-path", Input)
            input_widget.value = str(tmp_path / "does_not_exist")
            input_widget.focus()
            await pilot.press("enter")
            await pilot.pause()

            label = app.screen.query_one("#picker-current", Label)
            assert "introuvable" in str(label.content)

            app.screen.query_one("#picker-cancel").press()
            await pilot.pause()

    _run(scenario())
