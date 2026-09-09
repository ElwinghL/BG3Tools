"""`RichLog` avec sélection de texte maison (clic-glisser) et menu
contextuel (clic droit) Copier / Sélectionner tout.

`RichLog` ne supporte pas la sélection native de Textual au clic-glisser
dans cette version : le compositeur ne sait pas faire correspondre une
position écran à un offset dans son contenu pour ce widget
(`Screen.get_widget_and_offset_at` retourne toujours `None`, vérifié en
pratique) — `ALLOW_SELECT = True` sur `RichLog` n'y change rien, c'est une
limitation de Textual lui-même. On implémente donc ici notre propre
sélection : suivi de la position souris pendant le glisser, surlignage des
cellules concernées (en surchargeant `render_line`), et extraction du texte
correspondant pour la copie (déclenchée automatiquement au relâchement de
la souris, comme une sélection de terminal classique)."""

from __future__ import annotations

from rich.style import Style

from textual import events
from textual.strip import Strip
from textual.widgets import RichLog

from bg3_mod_tui.widgets.context_menu import ContextMenu

_MENU_ITEMS = [
    ("copy", "Copier"),
    ("select-all", "Sélectionner tout"),
]

_SELECTION_STYLE = Style(bgcolor="blue", color="white")


class ConsoleLog(RichLog):
    """`RichLog` en lecture seule, avec sélection de texte au clic-glisser
    (surlignage + copie automatique au relâchement) et un menu contextuel au
    clic droit proposant Copier (la sélection, ou tout le contenu à défaut)
    et Sélectionner tout."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._sel_anchor: tuple[int, int] | None = None
        self._sel_end: tuple[int, int] | None = None
        self._selecting = False

    # -- Sélection au clic-glisser -----------------------------------

    def _content_pos(self, event: events.MouseEvent) -> tuple[int, int] | None:
        """Position (ligne absolue dans le buffer, colonne) correspondant à
        `event`, ou None si le buffer est vide. La position est bornée au
        contenu réel (une ligne/colonne hors buffer est ramenée au bord)."""
        if not self.lines:
            return None
        offset = event.get_content_offset(self)
        if offset is None:
            region = self.content_region
            x = max(0, min(event.screen_x - region.x, region.width - 1))
            y = max(0, min(event.screen_y - region.y, region.height - 1))
        else:
            x, y = offset.x, offset.y

        scroll_x, scroll_y = self.scroll_offset
        row = max(0, min(y + scroll_y, len(self.lines) - 1))
        col = max(0, min(x + scroll_x, self.lines[row].cell_length))
        return row, col

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        pos = self._content_pos(event)
        if pos is None:
            return
        event.stop()
        self.capture_mouse()
        self._selecting = True
        self._sel_anchor = pos
        self._sel_end = pos
        self.refresh()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self._selecting:
            return
        pos = self._content_pos(event)
        if pos is None:
            return
        self._sel_end = pos
        self.refresh()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if not self._selecting:
            return
        self._selecting = False
        self.release_mouse()
        if self._sel_anchor != self._sel_end:
            text = self._get_selected_text()
            if text:
                self.app.copy_to_clipboard(text)

    def _select_all(self) -> None:
        if not self.lines:
            self._sel_anchor = self._sel_end = None
            return
        self._sel_anchor = (0, 0)
        self._sel_end = (len(self.lines) - 1, self.lines[-1].cell_length)
        self.refresh()

    def _clear_selection(self) -> None:
        self._sel_anchor = None
        self._sel_end = None
        self.refresh()

    def _get_selected_text(self) -> str:
        if self._sel_anchor is None or self._sel_end is None:
            return ""
        start, end = sorted([self._sel_anchor, self._sel_end])
        start_row, start_col = start
        end_row, end_col = end

        rows: list[str] = []
        for row in range(start_row, end_row + 1):
            line = self.lines[row]
            col_start = start_col if row == start_row else 0
            col_end = end_col if row == end_row else line.cell_length
            rows.append(line.crop(col_start, col_end).text)
        return "\n".join(rows)

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if self._sel_anchor is None or self._sel_end is None:
            return strip

        scroll_x, scroll_y = self.scroll_offset
        absolute_row = scroll_y + y
        start, end = sorted([self._sel_anchor, self._sel_end])
        start_row, start_col = start
        end_row, end_col = end

        if not (start_row <= absolute_row <= end_row):
            return strip

        col_start = start_col if absolute_row == start_row else 0
        col_end = end_col if absolute_row == end_row else strip.cell_length + scroll_x
        # `strip` est déjà recadrée pour l'affichage (colonnes relatives au
        # scroll horizontal) : on convertit les bornes absolues en bornes
        # visibles avant de les appliquer.
        visible_start = max(0, col_start - scroll_x)
        visible_end = max(0, min(col_end - scroll_x, strip.cell_length))
        if visible_start >= visible_end:
            return strip

        before = strip.crop(0, visible_start)
        middle = strip.crop(visible_start, visible_end).apply_style(_SELECTION_STYLE)
        after = strip.crop(visible_end, strip.cell_length)
        return Strip.join([before, middle, after])

    # -- Menu contextuel (clic droit) ---------------------------------

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
            self._select_all()

    def _copy_selection_or_all(self) -> None:
        text = self._get_selected_text() or "\n".join(line.text for line in self.lines)
        self.app.copy_to_clipboard(text)
