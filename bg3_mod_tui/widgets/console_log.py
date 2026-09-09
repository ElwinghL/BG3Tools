"""`RichLog` avec menu contextuel (clic droit) Copier / Sélectionner tout.

La sélection de texte à la souris (glisser-déposer) est déjà gérée
nativement par Textual sur ce widget ; on ajoute ici seulement le clic
droit, absent par défaut."""

from __future__ import annotations

from textual import events
from textual.widgets import RichLog

from bg3_mod_tui.widgets.context_menu import ContextMenu

_MENU_ITEMS = [
    ("copy", "Copier"),
    ("select-all", "Sélectionner tout"),
]


class ConsoleLog(RichLog):
    """`RichLog` en lecture seule, avec un menu contextuel au clic droit
    proposant Copier (la sélection, ou tout le contenu à défaut) et
    Sélectionner tout."""

    def on_click(self, event: events.Click) -> None:
        if event.button != 3:
            return
        event.stop()
        self.app.push_screen(
            ContextMenu(_MENU_ITEMS, (event.screen_x, event.screen_y)),
            self._handle_menu_choice,
        )

    def _handle_menu_choice(self, choice: str | None) -> None:
        if choice == "copy":
            self._copy_selection_or_all()
        elif choice == "select-all":
            self.text_select_all()

    def _copy_selection_or_all(self) -> None:
        selected = self.screen.get_selected_text()
        text = selected if selected else "\n".join(line.text for line in self.lines)
        self.app.copy_to_clipboard(text)
