"""Comparaison de versions de mods, tolérante aux formats hétérogènes
utilisés par Nexus Mods et mod.io — aucune norme n'est imposée aux auteurs
de mods : "1.2.3", "v1.2", "1.2.3.4", parfois du texte libre ("Release 3").

Utilisé par la règle de priorisation Nexus/Mod.io (voir TODO "Priorisation
Nexus / Mod.io") pour :
  1. décider si mod.io propose une version plus récente qu'une archive
     Nexus locale (`mod_pipeline.sync_modio_priority`) ;
  3. détecter, parmi les archives Nexus connues localement, celles devenues
     obsolètes par rapport à la version actuellement publiée sur Nexus
     (`mod_pipeline.check_nexus_updates`).
"""

from __future__ import annotations

import re

_NUMERIC_RE = re.compile(r"\d+")


def parse_version(raw: str | None) -> tuple[int, ...]:
    """Extrait la suite de composants numériques d'une chaîne de version
    libre (ex: "v1.12.3-beta" -> (1, 12, 3), "1-2-3" -> (1, 2, 3)), pour
    une comparaison numérique correcte plutôt qu'alphabétique (où la chaîne
    "10" est alphabétiquement avant "9"). Retourne un tuple vide si aucun
    chiffre n'est trouvé (version absente/vide, ou entièrement textuelle,
    ex: "Beta build")."""
    if not raw:
        return ()
    return tuple(int(n) for n in _NUMERIC_RE.findall(raw))


def is_newer(candidate: str | None, reference: str | None) -> bool:
    """True si `candidate` est une version strictement plus récente que
    `reference`, en comparant leurs composants numériques (voir
    `parse_version`) position par position — les tuples de longueurs
    différentes sont complétés à droite par des 0 avant comparaison (donc
    "1.2" est plus récent que "1.1.9", et "1.2.0" est égal à "1.2").

    Si l'un des deux ne contient aucun composant numérique exploitable, la
    comparaison n'est pas fiable : retourne False plutôt que de deviner —
    on ne déclenche jamais d'action automatique (téléchargement,
    changement d'origine...) sur une version illisible."""
    cand = parse_version(candidate)
    ref = parse_version(reference)
    if not cand or not ref:
        return False
    length = max(len(cand), len(ref))
    cand_padded = cand + (0,) * (length - len(cand))
    ref_padded = ref + (0,) * (length - len(ref))
    return cand_padded > ref_padded


def select_priority_source(nexus_version: str | None, modio_version: str | None) -> str:
    """Applique la « règle unique » du TODO : mod.io n'est prioritaire que
    s'il propose une version STRICTEMENT plus récente que celle connue côté
    Nexus. Retourne "modio" si `modio_version` est plus récent que
    `nexus_version`, sinon "nexus" (égalité, mod.io plus ancien, ou l'une
    des deux versions illisible — dans le doute, on ne bascule pas)."""
    return "modio" if is_newer(modio_version, nexus_version) else "nexus"
