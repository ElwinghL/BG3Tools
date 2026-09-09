"""Champ de saisie de chemin : un clic ouvre le sélecteur de dossier."""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Input


class PathInput(Input):
    """`Input` qui déclenche l'ouverture d'un sélecteur de dossier au clic,
    tout en restant éditable au clavier (saisie manuelle du chemin)."""

    class BrowseRequested(Message):
        """Émis lorsque l'utilisateur clique sur le champ pour parcourir."""

        def __init__(self, path_input: "PathInput") -> None:
            self.path_input = path_input
            super().__init__()

        @property
        def control(self) -> "PathInput":
            return self.path_input

    def on_click(self, event: events.Click) -> None:
        self.post_message(self.BrowseRequested(self))
