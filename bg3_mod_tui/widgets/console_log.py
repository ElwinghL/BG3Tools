"""Console de logs avec sélection de texte au clic-glisser qui fonctionne
réellement, plus un menu contextuel (clic droit) Copier / Sélectionner tout.

Précédemment basé sur `RichLog`, qui ne supporte pas la sélection native de
Textual au clic-glisser (`Screen.get_widget_and_offset_at()` renvoie
toujours `None` pour ce widget — vérifié par tests reproductibles,
comparaison directe avec `Static` dans le même harnais). Une sélection
maison (suivi souris + surlignage manuel) a été tentée par-dessus `RichLog`
mais restait défaillante en usage réel malgré des tests automatisés
concluants (`Pilot.mouse_down/hover/mouse_up` injecte les événements
directement dans Textual, sans passer par le vrai protocole de tracking
souris du terminal — un faux négatif possible qui n'a pas pu être
diagnostiqué plus avant sans accès au terminal réel de l'utilisateur).

Cette version change donc d'outil : `Static` (confirmé fonctionnel pour la
sélection native au clic-glisser) dans un `VerticalScroll`, qui gère le
défilement. Le contenu est un buffer de lignes (markup Rich conservé —
`[red]...[/red]`, codes couleur hex — tout comme avant) rejoint et poussé
dans le `Static` à chaque `write()`, avec défilement automatique vers le
bas."""

from __future__ import annotations

from textual import events
from textual.containers import VerticalScroll
from textual.widgets import Static

from bg3_mod_tui.widgets.context_menu import ContextMenu

_MENU_ITEMS = [
    ("copy", "Copier"),
    ("select-all", "Sélectionner tout"),
]


class ConsoleLog(VerticalScroll):
    """Console de logs en lecture seule : sélection de texte native au
    clic-glisser (via `Static`), défilement automatique vers le bas à
    chaque ligne ajoutée, et menu contextuel au clic droit proposant
    Copier (la sélection, ou tout le contenu à défaut) et Sélectionner
    tout."""

    DEFAULT_CSS = """
    ConsoleLog {
        & > Static {
            width: 100%;
            height: auto;
        }
    }
    """

    def __init__(
        self,
        *,
        max_lines: int | None = 1000,
        markup: bool = True,
        wrap: bool = True,
        highlight: bool = False,
        **kwargs,
    ) -> None:
        # `wrap`/`highlight` : acceptés pour compatibilité avec les appels
        # existants (signature calquée sur `RichLog`) mais sans effet
        # propre — `Static` gère lui-même le retour à la ligne, et il n'y a
        # pas d'équivalent au highlighter automatique de `RichLog` ici (nos
        # messages sont déjà colorés explicitement via markup).
        super().__init__(**kwargs)
        self._max_lines = max_lines
        self._markup = markup
        self._lines: list[str] = []

    def compose(self):
        yield Static("", markup=self._markup, id="_console_content")

    def write(self, text) -> None:
        """Ajoute une ligne au buffer (texte, éventuellement avec markup
        Rich) et fait défiler la console jusqu'en bas."""
        self._lines.append(str(text))
        if self._max_lines is not None and len(self._lines) > self._max_lines:
            self._lines = self._lines[-self._max_lines :]
        self.query_one("#_console_content", Static).update("\n".join(self._lines))
        self.scroll_end(animate=False)

    def clear(self) -> None:
        self._lines.clear()
        self.query_one("#_console_content", Static).update("")

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
            self.query_one("#_console_content", Static).text_select_all()

    def _copy_selection_or_all(self) -> None:
        selected = self.screen.get_selected_text()
        text = selected if selected else "\n".join(self._lines)
        self.app.copy_to_clipboard(text)
