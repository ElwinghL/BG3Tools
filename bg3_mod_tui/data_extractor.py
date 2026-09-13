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

**16b (implémenté partiellement)** : extraction réelle depuis le contenu des
`.pak`, en réutilisant `pak_reader.PakArchive` — voir `extract_pak_entities`
et son commentaire pour le périmètre couvert (dons/objets via
`Stats/Generated/Data/*.txt`) et volontairement non couvert (classes/sous-
classes LSX, objets via RootTemplates LSF). Testé sur un .pak SYNTHÉTIQUE
(pas de vrai .pak BG3 disponible dans cet environnement de dev).

**16c** : la fonction `documentation_index_to_json` pose déjà le format de
sortie voulu (une liste par type d'entité) pour les MENTIONS (16a) ;
`PakEntity` (16b) n'y est pas encore intégré — reste séparé pour l'instant,
à fusionner dans une future itération une fois validé contre de vrais
.pak."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from bg3_mod_tui.pak_reader import PakArchive
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


# --- 16b : extraction depuis le contenu réel des .pak -----------------
#
# Périmètre couvert, réutilisant `pak_reader.PakArchive` (déjà utilisé par
# `pak_metadata.py` pour meta.lsx/meta.lsf) plutôt que Divine.exe :
#
#   - dons (feats) et objets (armes/armures/objets) :
#     `Public/<Mod>/Stats/Generated/Data/{Feat,Weapon,Armor,Object}.txt` —
#     format "stats" texte de Larian (blocs `new entry "Nom"` / `type
#     "..."` / `data "Clé" "Valeur"`, documenté publiquement par la
#     communauté de modding DOS2/BG3, pas de spécification officielle
#     Larian). Implémenté et testé contre un `.pak` SYNTHÉTIQUE construit
#     à la main (voir `tests/test_data_extractor.py`) — **NON vérifié
#     contre un vrai `.pak` BG3** faute d'en avoir un disponible dans cet
#     environnement de dev (même réserve que celle déjà documentée sur
#     `pak_reader`/`pak_metadata`).
#
# Périmètre volontairement NON couvert (plutôt que deviner un format non
# vérifiable) :
#
#   - classes/sous-classes (`Public/<Mod>/Progression.lsx` et/ou
#     `ClassDescriptions.lsx`) : le schéma exact des nœuds (id du node
#     racine, noms d'attributs pour `ParentGuid`, structure des niveaux
#     de progression) n'est pas connu avec certitude ici — contrairement
#     au `meta.lsx` (`ModuleInfo`), aucun exemple réel n'a pu être
#     confirmé. Deviner ce schéma risquerait de produire un extracteur
#     silencieusement faux plutôt qu'un extracteur absent mais honnête.
#   - objets via `Public/<Mod>/RootTemplates/*.lsf` (gabarits, LSF
#     binaire) : contrairement à `meta.lsf` où l'on ne cherche qu'un UUID
#     isolé (`pak_reader.extract_uuid_from_lsf_bytes`), associer
#     correctement un GUID de RootTemplate à un nom d'objet exploitable
#     nécessiterait de parser la structure réelle des chunks LSF
#     (Names/Nodes/Attributes/Values), non implémentée dans ce projet.
#
# Ces deux pistes restent documentées ici pour un futur 16b-bis, mais ne
# sont pas couvertes par `extract_pak_entities` — un périmètre réduit mais
# fiable plutôt qu'une extraction complète mais non fiable.

# Chemins internes ciblés dans le .pak (relatifs, cherchés par suffixe via
# `PakArchive.find_suffix` — même technique que `pak_metadata` pour
# meta.lsx/meta.lsf, qui gère déjà le cas où le dossier de mod exact est
# inconnu à l'avance) et le type d'entité (`ENTITY_KINDS`) qu'ils
# alimentent.
_STATS_FILE_KINDS: dict[str, str] = {
    "stats/generated/data/feat.txt": "don",
    "stats/generated/data/weapon.txt": "objet",
    "stats/generated/data/armor.txt": "objet",
    "stats/generated/data/object.txt": "objet",
}

_STATS_NEW_ENTRY_RE = re.compile(r'new entry\s+"([^"]*)"')
_STATS_TYPE_RE = re.compile(r'^\s*type\s+"([^"]*)"', re.MULTILINE)
_STATS_DATA_RE = re.compile(r'^\s*data\s+"([^"]*)"\s*"([^"]*)"', re.MULTILINE)


@dataclass
class StatsEntry:
    """Une entrée du format "stats" texte de Larian (`new entry "Nom"` ...
    `type "..."` ... `data "Clé" "Valeur"` ...). `name` est l'identifiant
    Larian de l'entrée (pas un GUID — ce format n'en utilise pas, contrairement
    aux RootTemplates LSF)."""

    name: str
    type: str | None
    data: dict[str, str]


def parse_stats_entries(text: str) -> list[StatsEntry]:
    """Parse le format "stats" texte de Larian (utilisé par
    `Stats/Generated/Data/{Feat,Weapon,Armor,Object}.txt` dans un .pak) :
    une suite de blocs `new entry "Nom"`, chacun suivi de ses lignes
    `type "..."` et `data "Clé" "Valeur"` jusqu'au bloc suivant (ou la fin
    du texte). Un bloc sans `type` a `type=None` (rare mais pas une
    erreur — le format autorise l'omettre si `using` hérite d'une entrée
    de base, non géré ici). Retourne une liste vide si `text` ne contient
    aucun `new entry`."""
    entries: list[StatsEntry] = []
    matches = list(_STATS_NEW_ENTRY_RE.finditer(text))
    for index, match in enumerate(matches):
        name = match.group(1)
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[block_start:block_end]
        type_match = _STATS_TYPE_RE.search(block)
        data = dict(_STATS_DATA_RE.findall(block))
        entries.append(StatsEntry(name=name, type=type_match.group(1) if type_match else None, data=data))
    return entries


@dataclass
class PakEntity:
    """Une entité RÉELLE (16b), confirmée par lecture du contenu du .pak —
    contrairement à `EntityMention` (16a), qui n'est qu'une mention
    textuelle best-effort dans une description Nexus."""

    kind: str  # une des clés de `ENTITY_KINDS` ("don" ou "objet" ici — voir
    # le commentaire ci-dessus pour ce qui n'est PAS couvert par 16b
    name: str  # identifiant Larian de l'entrée stats (pas un GUID)
    label: str  # `DisplayName` si présent dans les données stats, sinon `name`
    source: str  # chemin interne exact dans le .pak (ex: "Public/MonMod/Stats/Generated/Data/Feat.txt")


def extract_pak_entities(pak_path: Path) -> list[PakEntity]:
    """Extraction réelle (16b) des dons/objets déclarés dans le contenu
    d'un .pak, via `pak_reader.PakArchive` — voir le commentaire "16b"
    ci-dessus pour le périmètre couvert (`Stats/Generated/Data/*.txt`) et
    volontairement non couvert (classes/sous-classes LSX, objets via
    RootTemplates LSF).

    Retourne une liste vide (pas une erreur) si aucun des fichiers stats
    ciblés n'est présent dans le .pak — un mod purement cosmétique ou sans
    nouveau don/objet n'a simplement rien à y extraire. Lève
    `pak_reader.PakReaderError` (`UnsupportedPakVersion`/`CorruptedPak`) si
    le .pak lui-même n'est pas exploitable nativement — même contrat que
    le reste de `pak_reader`, à l'appelant de replier sur Divine.exe s'il
    en a besoin."""
    entities: list[PakEntity] = []
    with PakArchive.open(pak_path) as pak:
        for suffix, kind in _STATS_FILE_KINDS.items():
            entry = pak.find_suffix(suffix)
            if entry is None:
                continue
            text = pak.read(entry).decode("utf-8", errors="replace")
            for stat in parse_stats_entries(text):
                label = stat.data.get("DisplayName") or stat.name
                entities.append(PakEntity(kind=kind, name=stat.name, label=label, source=entry.name))
    return entities
