"""Formatage aligné (colonnes de taille fixe) des lignes de log affichées
dans le RichLog du menu d'actions — nom du mod, version, statut."""

from __future__ import annotations

import re

from rich.markup import escape

from bg3_mod_tui.theme import LOG_COLOR_ERROR, LOG_COLOR_SUCCESS, LOG_COLOR_WARNING

NAME_WIDTH = 44
VERSION_WIDTH = 10
STATUS_WIDTH = 9

STATUS_SUCCES = "SUCCÈS"
STATUS_ECHEC = "ÉCHEC"
STATUS_IGNORE = "IGNORÉ"
STATUS_EXAMEN = "EXAMEN"

_STATUS_COLORS = {
    STATUS_SUCCES: LOG_COLOR_SUCCESS,
    STATUS_ECHEC: LOG_COLOR_ERROR,
    STATUS_IGNORE: LOG_COLOR_WARNING,
    STATUS_EXAMEN: LOG_COLOR_WARNING,
}


def _pad(text: str, width: int) -> str:
    text = str(text)
    if len(text) > width:
        text = text[: max(width - 1, 0)] + "…"
    return text.ljust(width)


def fmt_row(name: str, status: str, *, version: str = "", detail: str = "") -> str:
    """Formate une ligne de log en colonnes alignées :
    `<nom>  <version>  <statut>  <détail>`.

    `name`/`version`/`detail` viennent de sources externes (nom de mod
    Nexus/mod.io, nom de fichier téléchargé, message d'erreur...) et
    peuvent donc contenir des crochets (ex: mod nommé littéralement
    "[Aza] NPC Redesign...") — échappés pour ne pas être interprétés comme
    du balisage Rich (tag inconnu avalé silencieusement, ou pire cassant
    l'alignement des colonnes suivantes). `status` reste non échappé : il
    ne vaut jamais qu'une des constantes `STATUS_*` ci-dessus."""
    color = _STATUS_COLORS.get(status, "white")
    parts = [escape(_pad(name, NAME_WIDTH)), escape(_pad(version, VERSION_WIDTH))]
    parts.append(f"[{color}]{_pad(status, STATUS_WIDTH)}[/{color}]")
    if detail:
        parts.append(escape(detail))
    return " ".join(parts)


# Lignes d'accès de `python -m http.server`, ex :
# `127.0.0.1 - - [10/Sep/2026 15:23:45] "GET / HTTP/1.1" 200 -`
_HTTP_LOG_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) (?P<proto>[^"]+)" '
    r'(?P<status>\d{3}) (?P<size>\S+)$'
)


def fmt_http_log_line(line: str) -> str:
    """Reformate une ligne de log de `python -m http.server` (console Web)
    en colonnes lisibles et colorées par code de statut. Nécessaire car ces
    lignes contiennent des crochets (l'horodatage, ex. `[10/Sep/2026
    ...]`) que le balisage Rich interpréterait sinon comme des tags,
    cassant l'affichage — d'où le passage par cette regex plutôt que
    l'affichage brut. Les lignes qui ne correspondent pas au format
    attendu (erreurs internes du serveur, etc.) sont renvoyées telles
    quelles, crochets échappés pour rester sûres vis-à-vis du markup."""
    match = _HTTP_LOG_RE.match(line)
    if match is None:
        return escape(line)

    status = int(match["status"])
    if status < 400:
        color = LOG_COLOR_SUCCESS
    elif status < 500:
        color = LOG_COLOR_WARNING
    else:
        color = LOG_COLOR_ERROR

    return (
        f"[dim]{escape(match['ts'])}[/dim]  "
        f"[bold]{_pad(match['method'], 6)}[/bold] "
        f"{escape(match['path'])}  "
        f"[{color}]{status}[/{color}]"
    )
