"""Icône "internet" cliquable (planète avec méridiens), rendue comme une
vraie image (PNG, via `textual-image` — Sixel/Kitty/iTerm selon le
terminal, repli en blocs Unicode sinon) plutôt qu'un caractère de police :
un caractère seul ne peut pas être agrandi dans un terminal (limite
physique du rendu texte), et un emoji plein-couleur ne peut pas changer de
couleur via CSS. Trois fichiers pré-colorés (voir `icons/`) remplacent
donc le glyphe unique coloré dynamiquement."""

from __future__ import annotations

from pathlib import Path

from textual import events
from textual.message import Message
from textual_image.widget import AutoImage as Image
from textual_image.widget import AutoRenderable

ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "icons"

STATE_ICONS = {
    "success": ICONS_DIR / "success.png",
    "warning": ICONS_DIR / "warn.png",
    "error": ICONS_DIR / "error.png",
}


class PlanetIcon(Image, Renderable=AutoRenderable):
    """Icône "planète" cliquable, avec un fichier par état (voir
    `STATE_ICONS`) — pas de bordure ni de fond, juste l'image."""

    class Clicked(Message):
        """Émis au clic — équivalent de `Button.Pressed` pour ce widget."""

        def __init__(self, planet_icon: "PlanetIcon") -> None:
            self.planet_icon = planet_icon
            super().__init__()

        @property
        def control(self) -> "PlanetIcon":
            return self.planet_icon

    def __init__(self, state: str = "warning", **kwargs) -> None:
        super().__init__(STATE_ICONS[state], **kwargs)
        self._state = state

    def set_state(self, state: str) -> None:
        if state not in STATE_ICONS:
            raise ValueError(f"État inconnu : {state!r} (attendu : {sorted(STATE_ICONS)})")
        self._state = state
        self.image = STATE_ICONS[state]

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.post_message(self.Clicked(self))
