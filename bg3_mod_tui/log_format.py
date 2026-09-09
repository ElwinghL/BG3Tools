"""Formatage aligné (colonnes de taille fixe) des lignes de log affichées
dans le RichLog du menu d'actions — nom du mod, version, statut."""

from __future__ import annotations

NAME_WIDTH = 44
VERSION_WIDTH = 10
STATUS_WIDTH = 9

STATUS_SUCCES = "SUCCÈS"
STATUS_ECHEC = "ÉCHEC"
STATUS_IGNORE = "IGNORÉ"
STATUS_EXAMEN = "EXAMEN"

_STATUS_COLORS = {
    STATUS_SUCCES: "green",
    STATUS_ECHEC: "red",
    STATUS_IGNORE: "yellow",
    STATUS_EXAMEN: "yellow",
}


def _pad(text: str, width: int) -> str:
    text = str(text)
    if len(text) > width:
        text = text[: max(width - 1, 0)] + "…"
    return text.ljust(width)


def fmt_row(name: str, status: str, *, version: str = "", detail: str = "") -> str:
    """Formate une ligne de log en colonnes alignées :
    `<nom>  <version>  <statut>  <détail>`."""
    color = _STATUS_COLORS.get(status, "white")
    parts = [_pad(name, NAME_WIDTH), _pad(version, VERSION_WIDTH)]
    parts.append(f"[{color}]{_pad(status, STATUS_WIDTH)}[/{color}]")
    if detail:
        parts.append(detail)
    return " ".join(parts)
