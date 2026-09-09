"""Menu contextuel générique (clic droit), positionné au point de clic."""

from __future__ import annotations

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button


class ContextMenu(ModalScreen[str | None]):
    """Petit menu déroulant affiché au point de clic droit. Se ferme sans
    action si on clique en dehors ou appuie sur Échap ; sinon renvoie l'id
    de l'option choisie (via `dismiss`)."""

    CSS = """
    ContextMenu {
        background: transparent;
    }
    ContextMenu #context-menu-box {
        width: auto;
        height: auto;
        border: round $accent;
        background: $panel;
        padding: 0 1;
    }
    ContextMenu #context-menu-box Button {
        width: 100%;
        min-width: 22;
        height: 1;
        border: none;
        background: $panel;
        content-align: left middle;
    }
    ContextMenu #context-menu-box Button:hover {
        background: $accent;
    }
    """

    def __init__(self, items: list[tuple[str, str]], position: tuple[int, int]) -> None:
        """`items` : liste de `(id, libellé)`. `position` : coordonnées
        (colonne, ligne) écran où ancrer le menu (typiquement celles du
        clic droit)."""
        super().__init__()
        self._items = items
        self._position = position

    def compose(self) -> ComposeResult:
        with Vertical(id="context-menu-box"):
            for item_id, label in self._items:
                yield Button(label, id=f"ctx-{item_id}")

    def on_mount(self) -> None:
        box = self.query_one("#context-menu-box")
        x, y = self._position
        box.styles.offset = (x, y)

    def on_click(self, event: events.Click) -> None:
        if event.widget is self:
            self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)

    @on(Button.Pressed)
    def handle_choice(self, event: Button.Pressed) -> None:
        event.stop()
        assert event.button.id is not None
        self.dismiss(event.button.id.removeprefix("ctx-"))
