"""Sélecteur de dossier en TUI : parcours d'une arborescence de répertoires,
avec possibilité de saisir directement un chemin pour s'y rendre."""

from __future__ import annotations

from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label


class DirectoryPickerScreen(ModalScreen[str | None]):
    """Fenêtre modale de sélection de dossier.

    Retourne le chemin choisi (str) via `dismiss()`, ou None si annulé.
    """

    CSS = """
    DirectoryPickerScreen {
        align: center middle;
    }
    #picker-box {
        width: 90%;
        height: 90%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #picker-tree {
        height: 1fr;
        border: round $panel;
        margin-top: 1;
    }
    #picker-current {
        margin-top: 1;
        height: auto;
    }
    #picker-buttons {
        height: auto;
        margin-top: 1;
    }
    #picker-buttons Button {
        margin-right: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Annuler")]

    def __init__(self, initial_path: str = "") -> None:
        super().__init__()
        self._root_path = self._compute_root(initial_path)
        self._selected_path = self._root_path

    @staticmethod
    def _compute_root(path_str: str) -> Path:
        candidate = Path(path_str).expanduser() if path_str.strip() else None
        if candidate is not None:
            if candidate.is_dir():
                return candidate
            if candidate.parent.is_dir():
                return candidate.parent
        home = Path.home()
        if home.is_dir():
            return home
        if candidate is not None and candidate.anchor:
            return Path(candidate.anchor)
        return Path("/")

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Label("Choisir un dossier", classes="title")
            yield Input(value=str(self._root_path), id="picker-manual-path")
            yield DirectoryTree(str(self._root_path), id="picker-tree")
            yield Label(f"Dossier sélectionné : {self._selected_path}", id="picker-current")
            with Horizontal(id="picker-buttons"):
                yield Button("Aller à ce chemin", id="picker-goto")
                yield Button("Choisir ce dossier", id="picker-choose", variant="primary")
                yield Button("Annuler", id="picker-cancel")

    def _set_selected(self, path: Path) -> None:
        self._selected_path = path
        self.query_one("#picker-current", Label).update(f"Dossier sélectionné : {path}")

    @on(DirectoryTree.DirectorySelected, "#picker-tree")
    def handle_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self._set_selected(event.path)

    @on(Input.Submitted, "#picker-manual-path")
    def handle_manual_path_submitted(self) -> None:
        self._goto_manual_path()

    @on(Button.Pressed, "#picker-goto")
    def handle_goto(self) -> None:
        self._goto_manual_path()

    def _goto_manual_path(self) -> None:
        raw = self.query_one("#picker-manual-path", Input).value.strip()
        path = Path(raw).expanduser()
        current_status = self.query_one("#picker-current", Label)
        if not path.is_dir():
            current_status.update(f"[red]Dossier introuvable : {path}[/red]")
            return
        self.query_one("#picker-tree", DirectoryTree).path = str(path)
        self._set_selected(path)

    @on(Button.Pressed, "#picker-choose")
    def handle_choose(self) -> None:
        self.dismiss(str(self._selected_path))

    @on(Button.Pressed, "#picker-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
