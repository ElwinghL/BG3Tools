"""`data-extractor` (TODO.md section 16) : extraction JSON des
classes/sous-classes/dons/objets ajoutés par nos mods installés.

**16a (implémenté ici)** : parcourt uniquement la DOCUMENTATION des mods
déjà installés — `mods_inventory.json` (voir `inventory.build_inventory`,
association .pak <-> archive/ID Nexus par nom de fichier) et, quand un ID
Nexus est connu, le résumé du mod via l'API Nexus (`NexusMod.summary`,
`providers/nexus.py`) — SANS jamais ouvrir/décompresser le contenu binaire
d'un `.pak`. Les classes/sous-classes/dons/objets ne sont donc ici que des
MENTIONS textuelles best-effort (voir `scan_entity_mentions`), pas des
entités confirmées par GUID.

**16b (réservé, pas implémenté)** : extraction réelle depuis le contenu des
`.pak`, en réutilisant `pak_reader.PakArchive` — voir `extract_pak_entities`
ci-dessous et son commentaire pour les pistes (fichiers internes visés).

**16c** : la fonction `documentation_index_to_json` pose déjà le format de
sortie voulu (une liste par type d'entité) ; 16b viendra remplacer/enrichir
les entrées "mention" par des entités réelles (GUID, nom exact) sans changer
cette structure globale."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bg3_mod_tui.providers.nexus import NexusAPIError, NexusClient

ProgressFn = Callable[[str], None]
_NOOP_PROGRESS: ProgressFn = lambda _msg: None

# Les 4 types d'entités visés par la section 16 du TODO, et la clé JSON
# (pluriel) sous laquelle leurs mentions/entités sont regroupées en sortie
# (16c) — un seul endroit à modifier si un type d'entité est ajouté un jour.
ENTITY_KINDS: tuple[str, ...] = ("classe", "sous_classe", "don", "objet")

_ENTITY_JSON_KEYS: dict[str, str] = {
    "classe": "classes",
    "sous_classe": "sous_classes",
    "don": "dons",
    "objet": "objets",
}

# Expressions reconnues dans un texte libre (résumé Nexus) pour chaque type
# d'entité — volontairement des expressions multi-mots plutôt que des mots
# isolés ("don", "objet", "classe" sont des mots beaucoup trop courants en
# français courant pour servir de signal fiable seuls) : mieux vaut rater
# une mention que remonter silencieusement un faux positif comme s'il
# s'agissait d'une donnée fiable.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "classe": ("nouvelle classe", "new class"),
    "sous_classe": ("nouvelle sous-classe", "nouvelle sous classe", "new subclass", "subclass"),
    "don": ("nouveau don", "nouveaux dons", "new feat"),
    "objet": (
        "nouvel objet",
        "nouvelle arme",
        "nouvelle armure",
        "new item",
        "new weapon",
        "new armor",
    ),
}

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _compile_keyword_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE)


_KEYWORD_PATTERNS: dict[str, re.Pattern[str]] = {
    kind: _compile_keyword_pattern(words) for kind, words in _KEYWORDS.items()
}


@dataclass
class EntityMention:
    """Mention best-effort d'une entité dans un texte libre — pas encore
    une entité confirmée (pas de GUID, voir 16b)."""

    kind: str  # une des clés de `ENTITY_KINDS`
    label: str  # phrase source où l'expression a été repérée
    source: str  # "nexus_summary" (seule source gérée par 16a)


@dataclass
class ModDocumentation:
    """Documentation best-effort d'un mod installé (16a) : identité connue
    via `mods_inventory.json` (voir `inventory.build_inventory`) + mentions
    d'entités repérées dans sa description Nexus, si disponible."""

    pak_file: str
    mod_name: str
    nexus_mod_id: int | None = None
    nexus_url: str | None = None
    version: str | None = None
    mentions: list[EntityMention] = field(default_factory=list)


def scan_entity_mentions(text: str) -> list[EntityMention]:
    """Repère, phrase par phrase, les mentions best-effort de nouvelles
    classes/sous-classes/dons/objets dans `text` (typiquement
    `NexusMod.summary`) — voir `_KEYWORDS` pour les expressions reconnues.

    Dédoublonne les phrases identiques : une même mention répétée dans le
    texte ne produit qu'une seule entrée. Retourne une liste vide si `text`
    est vide/None ou ne contient aucune expression reconnue — ce n'est pas
    une erreur, juste l'absence d'indice exploitable sans lire le .pak."""
    if not text:
        return []
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    mentions: list[EntityMention] = []
    seen: set[tuple[str, str]] = set()
    for sentence in sentences:
        for kind, pattern in _KEYWORD_PATTERNS.items():
            if not pattern.search(sentence):
                continue
            key = (kind, sentence)
            if key in seen:
                continue
            seen.add(key)
            mentions.append(EntityMention(kind=kind, label=sentence, source="nexus_summary"))
    return mentions


def _archives_by_name(inventory: dict) -> dict[str, dict]:
    return {a["file"]: a for a in inventory.get("archives", [])}


def build_documentation_index(
    inventory: dict,
    *,
    nexus_client: NexusClient | None = None,
    on_progress: ProgressFn = _NOOP_PROGRESS,
) -> list[ModDocumentation]:
    """Construit la documentation best-effort de chaque .pak actuellement
    installé (`inventory["paks"]`, voir `inventory.build_inventory`).

    `nexus_client` est optionnel (nécessite une clé API Nexus, voir
    `providers.nexus.NexusClient`) : sans lui, ou pour un .pak dont
    l'archive d'origine n'a pas pu être associée à un ID Nexus (voir
    `inventory.match_archive_origin`), le mod est quand même inclus dans le
    résultat mais avec `mentions` vide — 16a reste utile même hors-ligne
    (au minimum : la liste des mods installés avec leur origine connue),
    l'enrichissement par description Nexus est un bonus, pas un prérequis.

    Un échec Nexus (mod introuvable, clé invalide, réseau) sur un mod
    donné est journalisé via `on_progress` et n'interrompt pas le parcours
    des autres mods (même logique de tolérance que
    `pak_metadata.build_deployed_uuid_index`)."""
    archives = _archives_by_name(inventory)
    paks = inventory.get("paks", [])
    on_progress(f"Parcours de la documentation de {len(paks)} .pak installé(s)...")

    entries: list[ModDocumentation] = []
    for pak in paks:
        archive = archives.get(pak.get("matched_archive") or "")
        mod_name = (archive.get("mod_name_guess") if archive else None) or Path(pak["file"]).stem
        nexus_mod_id = archive.get("nexus_mod_id") if archive else None
        nexus_url = archive.get("nexus_url") if archive else None
        version = archive.get("version") if archive else None

        mentions: list[EntityMention] = []
        if nexus_client is not None and nexus_mod_id is not None:
            try:
                mod_info = nexus_client.mod_info(nexus_mod_id)
            except NexusAPIError as exc:
                on_progress(f"  {mod_name} : description Nexus indisponible ({exc}).")
            else:
                mentions = scan_entity_mentions(mod_info.summary)

        entries.append(
            ModDocumentation(
                pak_file=pak["file"],
                mod_name=mod_name,
                nexus_mod_id=nexus_mod_id,
                nexus_url=nexus_url,
                version=version,
                mentions=mentions,
            )
        )
    return entries


def documentation_index_to_json(entries: list[ModDocumentation]) -> dict:
    """Regroupe les mentions de tous les mods par type d'entité (16c) :

        {
          "generated_at": "...",
          "classes": [{"mod_name", "pak_file", "nexus_mod_id", "nexus_url",
                        "label", "source"}, ...],
          "sous_classes": [...],
          "dons": [...],
          "objets": [...],
        }

    Volontairement pas de champ "guid" tant que 16b (lecture réelle des
    .pak, seule source capable de fournir un GUID fiable) n'est pas
    implémenté — ajouter un champ vide/None laisserait croire à une
    fiabilité que 16a n'a pas."""
    grouped: dict[str, list[dict]] = {key: [] for key in _ENTITY_JSON_KEYS.values()}
    for mod in entries:
        for mention in mod.mentions:
            grouped[_ENTITY_JSON_KEYS[mention.kind]].append(
                {
                    "mod_name": mod.mod_name,
                    "pak_file": mod.pak_file,
                    "nexus_mod_id": mod.nexus_mod_id,
                    "nexus_url": mod.nexus_url,
                    "label": mention.label,
                    "source": mention.source,
                }
            )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mods": [asdict(mod) for mod in entries],
        **grouped,
    }


def save_documentation_index(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- 16b (réservé, pas implémenté) -----------------------------------
#
# Étendre l'extraction au contenu réel des .pak, en réutilisant
# `pak_reader.PakArchive` (déjà utilisé par `pak_metadata.py` pour
# meta.lsx/meta.lsf) plutôt que Divine.exe, pour rester rapide (pas de
# sous-processus/extraction sur disque pour chaque .pak).
#
# Pistes (NON vérifiées contre un vrai .pak BG3 dans cet environnement de
# dev — même réserve que celle déjà documentée sur `pak_reader`/
# `pak_metadata` : à confirmer avant de s'y fier) :
#   - classes/sous-classes : `Public/<Mod>/Progression.lsx` et/ou
#     `Public/<Mod>/ClassDescriptions.lsx` — LSX (XML), le même parsing
#     `xml.etree.ElementTree` que `pak_metadata.parse_meta_lsx` s'applique,
#     mais avec un schéma de nœuds différent de `ModuleInfo` (à documenter
#     une fois vérifié contre un vrai fichier).
#   - dons (feats) : `Public/<Mod>/Stats/Generated/Data/Feat.txt` et/ou
#     `FeatDescriptions.lsx` — le `.txt` est le format "stats" BG3 (pas
#     XML, blocs `new entry "..."` / `data "..." "..."`), qui nécessite un
#     parseur dédié, pas encore écrit ici.
#   - objets : `Public/<Mod>/Stats/Generated/Data/{Weapon,Armor,Object}.txt`
#     (même format "stats" texte) et/ou `Public/<Mod>/RootTemplates/*.lsf`
#     pour les gabarits d'objets (LSF binaire, comme `meta.lsf` — voir
#     `pak_reader.extract_uuid_from_lsf_bytes` pour la limite déjà connue
#     de l'approche regex sur du LSF).
#   - localiser ces fichiers dans le .pak via `PakArchive.find_suffix`
#     (même technique que `pak_metadata` pour meta.lsx/meta.lsf, qui gère
#     déjà le cas où le dossier de mod exact est inconnu à l'avance).
#
# `extract_pak_entities` ci-dessous n'est qu'un point d'entrée réservé,
# volontairement non implémenté (NotImplementedError) plutôt qu'une
# extraction approximative qui laisserait croire à un résultat fiable.


def extract_pak_entities(pak_path: Path) -> list[EntityMention]:  # noqa: ARG001
    """RÉSERVÉ pour 16b : extraction d'entités réelles (classes/sous-
    classes/dons/objets, identifiées par GUID) depuis le contenu du .pak
    `pak_path`, via `pak_reader.PakArchive` — voir le commentaire "16b"
    ci-dessus pour les fichiers internes visés. Pas encore implémenté."""
    raise NotImplementedError(
        "16b : extraction depuis le contenu réel des .pak pas encore implémentée "
        "(voir bg3_mod_tui/data_extractor.py, section 16b)."
    )
