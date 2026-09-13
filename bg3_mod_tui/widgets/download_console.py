"""Console dédiée aux téléchargements parallèles (sous-tâche 5c du TODO
"Téléchargements parallèles") : contrairement à `ConsoleLog` (un journal qui
ne fait qu'accumuler des lignes), cette console affiche UNE ligne par
téléchargement actif — un par thread du pool Nexus/mod.io (voir
`mod_pipeline.download_mods_from_links_file`/`download_subscribed_modio_mods`,
paramètre `on_download_progress`) — mise à jour en place au fil de sa
progression, puis retirée à sa fin (succès ou échec).

Chaque ligne est identifiée par un "slot" (chaîne arbitraire mais stable
pour la durée d'un téléchargement, ex: "nexus-42-1337" ou "modio-5990151",
voir `mod_pipeline.DownloadProgressFn`) plutôt que par sa position — deux
téléchargements peuvent se terminer dans un ordre différent de celui où ils
ont démarré, un simple `write()` façon `ConsoleLog` ne conviendrait pas ici.
"""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static

_EMPTY_MESSAGE = "(aucun téléchargement en cours)"


def _human_size(size_bytes: int) -> str:
    """Formate une taille en octets en unité lisible (o/Ko/Mo/Go) — même
    logique que `mod_pipeline._human_size`, dupliquée ici pour ne pas faire
    dépendre ce widget d'un module qui n'a par ailleurs rien d'une brique
    UI (import circulaire à éviter : `mod_pipeline` ne doit pas dépendre de
    Textual)."""
    size = float(size_bytes)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{size:.1f} {unit}" if unit != "o" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} Go"


def _progress_bar(pct: int, width: int = 20) -> str:
    filled = min(width, max(0, pct * width // 100))
    return "█" * filled + "░" * (width - filled)


class DownloadProgressConsole(VerticalScroll):
    """Une ligne par téléchargement actif, avec barre de progression et
    taille téléchargée/totale (ou juste la taille téléchargée si le serveur
    n'a pas fourni de `Content-Length`). Toutes les méthodes publiques
    doivent être appelées depuis le thread UI principal (ex: via
    `App.call_from_thread` depuis le thread de téléchargement concerné —
    voir `ActionsScreen`), comme le reste des widgets Textual."""

    DEFAULT_CSS = """
    DownloadProgressConsole {
        & > Static {
            width: 100%;
            height: auto;
        }
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Dict plutôt que liste : ordre d'insertion préservé (Python 3.7+),
        # mais mise à jour/retrait en place par clé (`slot_id`) en O(1), sans
        # avoir à rechercher la bonne ligne à chaque appel.
        self._slots: dict[str, str] = {}

    def compose(self):
        yield Static(_EMPTY_MESSAGE, id="_download_progress_content")

    def update_progress(
        self, slot_id: str, label: str, downloaded: int | None, total: int | None
    ) -> None:
        """Met à jour (ou crée) la ligne de progression du slot `slot_id`.
        `downloaded=None` retire la ligne (téléchargement terminé, succès ou
        échec — voir `mod_pipeline.DownloadProgressFn`)."""
        if downloaded is None:
            self._slots.pop(slot_id, None)
        elif total:
            pct = min(100, downloaded * 100 // total)
            self._slots[slot_id] = (
                f"⬇ {label}  {_progress_bar(pct)}  {pct:>3}%  "
                f"({_human_size(downloaded)} / {_human_size(total)})"
            )
        else:
            # Taille totale inconnue (pas de Content-Length) : pas de
            # pourcentage ni de barre fiables, juste la taille téléchargée
            # jusqu'ici.
            self._slots[slot_id] = f"⬇ {label}  {_human_size(downloaded)}"
        self._refresh_content()

    def clear(self) -> None:
        self._slots.clear()
        self._refresh_content()

    def _refresh_content(self) -> None:
        """Réécrit le contenu du `Static` interne à partir de `self._slots`.

        Nommée `_refresh_content` et non `_render` : `Widget._render(self)
        -> Visual` est une méthode interne de Textual (utilisée par le
        compositeur pour obtenir le `Visual` à peindre). La redéfinir ici
        avec une signature incompatible (retourne `None` au lieu d'un
        `Visual`) faisait planter tout rendu de ce widget avec
        `AttributeError: 'NoneType' object has no attribute
        'render_strips'` dès qu'il devenait effectivement visible — ce qui
        n'arrive qu'au premier affichage de son `TabPane` "Téléchargements"
        (les autres onglets ne le déclenchent jamais), d'où un plantage
        systématique au clic sur cet onglet et nulle part ailleurs."""
        content = self.query_one("#_download_progress_content", Static)
        content.update("\n".join(self._slots.values()) if self._slots else _EMPTY_MESSAGE)
