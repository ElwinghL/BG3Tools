"""Présélection automatique pour le wizard de choix de fichiers Nexus
(`screens.actions.NexusFileSelectionScreen`).

Certains mods (ex: les collections de préréglages "Mantis'...") publient
plusieurs fichiers MUTUELLEMENT EXCLUSIFS pour un même mod : une version
"simple", une version compatible avec Unique Tav (UT), une version
compatible avec Eye of the Beholder (EOTB), et parfois une version
combinée UT+EOTB. Le wizard cochait jusque-là TOUS les candidats par
défaut (voir `NexusFileSelectionScreen.compose`) : il était donc facile
d'installer par erreur plusieurs variantes incompatibles à la fois en
validant sans tout décocher à la main — repéré par Elwingh sur plusieurs
mods Mantis ("j'ai fait des erreurs plus tôt").

Elwingh a confirmé avoir Unique Tav ET Eye of the Beholder installés : la
présélection privilégie donc systématiquement la variante la plus
compatible avec les deux, plutôt que de tout cocher par défaut — mais
reste un simple PRÉ-cochage dans le wizard (l'utilisateur peut toujours
ajuster avant de valider), pas un choix silencieux qui contournerait le
wizard.
"""

from __future__ import annotations

import re

_EOTB_RE = re.compile(r"\bEOTB\b|EYE\s+OF\s+THE\s+BEHOLDER", re.IGNORECASE)
_UT_RE = re.compile(r"\bUT\b|UNIQUE\s*TAV", re.IGNORECASE)


def infer_ut_eotb_preselection(candidates: list[tuple[int, str]]) -> set[int] | None:
    """Retourne l'ensemble des `file_id` à précocher par défaut si
    `candidates` (couples file_id/nom de fichier, tels que renvoyés par
    `NexusClient.latest_files`) ressemble à un groupe de variantes
    Simple/UT/EOTB/UT+EOTB (au moins un nom matchant UT ou EOTB) ; `None`
    sinon, pour laisser le comportement par défaut (tout coché) inchangé —
    cette heuristique ne doit s'appliquer qu'à ce cas précis, pas à un
    choix de variantes générique sans rapport (ex: "X2 Increase"/"X5
    Increase", tailles d'icônes, résolutions de texture...).

    - Un seul fichier nommant À LA FOIS UT et EOTB (la variante combinée) :
      lui seul est présélectionné.
    - Sinon, des fichiers UT-only et EOTB-only séparés (pas de combiné) :
      les deux sont présélectionnés (Elwingh a les deux mods installés),
      la variante "simple" ne l'est pas.
    """
    flags = {
        file_id: (bool(_UT_RE.search(name)), bool(_EOTB_RE.search(name)))
        for file_id, name in candidates
    }
    if not any(is_ut or is_eotb for is_ut, is_eotb in flags.values()):
        return None

    combo_ids = {file_id for file_id, (is_ut, is_eotb) in flags.items() if is_ut and is_eotb}
    if combo_ids:
        return combo_ids

    return {file_id for file_id, (is_ut, is_eotb) in flags.items() if is_ut or is_eotb}
