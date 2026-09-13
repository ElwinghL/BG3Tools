"""Audit STATIQUE (pas besoin du jeu lancé) de compatibilité et de syntaxe
des mods vis-à-vis du BG3 Compatibility Framework — TODO `.claude/TODO.md`
section 18 ("Audit de compatibilité et de syntaxe des mods"), sous-tâches
18a/18b/18c (18d — vérification en jeu — est explicitement hors scope de ce
module, voir `screens/actions.py` pour un éventuel TODO explicite).

Le Compatibility Framework (`Tools/BG3-Compatibility-Framework/`, submodule
git de ce dépôt — voir `Tools/TOOLS.md`) permet à un mod d'injecter des
classes/sous-classes/sorts/passifs dans les tables du jeu SANS écraser les
autres mods actifs, via deux mécanismes concurrents documentés dans le
submodule :

1. **Déclaratif** : un fichier `ScriptExtender/CompatibilityFrameworkConfig.
   {json,yaml,yml}` à la racine du mod, auto-découvert par le Framework pour
   CHAQUE mod chargé (voir `ConfigLayer/_ConfigLoader.lua` du submodule) —
   aucune dépendance `meta.lsx` n'est strictement requise pour que ce
   mécanisme fonctionne, mais en déclarer une reste la bonne pratique
   (message d'erreur clair si le Framework n'est pas chargé).
2. **Impératif** : appel direct à l'API Lua exposée par le Framework
   (`Mods.SubclassCompatibilityFramework.Api.*`) depuis le propre
   `ScriptExtender/Lua/BootstrapServer.lua`/`BootstrapClient.lua` du mod —
   c'est la seule voie pour AJOUTER une sous-classe (`InsertSubClasses`) :
   `ProgressionHandler.lua` du submodule montre que la voie JSON
   n'applique QUE `"Action": "Remove"` pour les sous-classes (`if
   data.Action ~= "Remove" then ... return`) — un `"Action": "Insert"` sur
   une entrée `Subclasses` du JSON est silencieusement ignoré. Ce module
   détecte spécifiquement ce piège (voir `_check_progressions`).

Toutes les constantes de vocabulaire ci-dessous (sections JSON connues,
mots-clés d'action, noms de fonctions de l'API Lua) sont extraites
directement du code source du submodule tel qu'épinglé dans ce dépôt (commit
figé dans `.gitmodules`/l'index git) — PAS d'un wiki externe non versionné.
Si le Framework évolue (nouvelle fonction API, nouvelle section JSON), ces
listes devront être mises à jour manuellement après un `git submodule
update` — un nom absent de ces listes est traité comme "inconnu"
(avertissement/erreur), donc un faux positif est possible après une mise à
jour du submodule tant que ce fichier n'est pas synchronisé.

LIMITES IMPORTANTES (à lire avant de faire confiance à ce rapport) :

- **Lecture native uniquement** (`pak_reader.PakArchive`, mmap + parsing
  Python pur du format LSPK) : PAS de repli automatique sur Divine.exe
  contrairement à `pak_metadata.py` — un .pak dans un format non géré
  nativement (version LSPK/LSF inattendue) est signalé en erreur plutôt que
  vérifié via Divine.exe. Voir `pak_reader.py` pour les mêmes incertitudes
  de format non validées empiriquement contre un vrai .pak BG3.
- **YAML** : ce projet n'a PAS PyYAML en dépendance (voir `pyproject.toml`).
  Si le module `yaml` est importable dans l'environnement d'exécution, la
  syntaxe est validée normalement (`yaml.safe_load`) ; sinon, un
  avertissement explicite est émis et un repli regex très approximatif
  scanne quand même le texte brut à la recherche de GUIDs manifestement
  invalides (voir `_scan_yaml_text_fallback`) — pas une validation
  syntaxique réelle.
- **`ParentGuid` de sous-classe (18b)** : le schéma JSON réel du Framework
  n'a pas de clé littéralement nommée `ParentGuid` — la relation
  parent/enfant est portée par l'imbrication (`Progressions[].UUID` est
  déjà la classe/progression parente des `Subclasses[]` qu'elle contient).
  Aucun référentiel des GUIDs vanilla n'existe dans ce dépôt (recherché,
  absent) : la cohérence n'est donc vérifiée qu'ENTRE mods installés
  scannés dans le même passage (voir `audit_installed_mods`,
  `_check_subclass_parent_consistency`) — une progression non trouvée
  parmi les mods scannés n'est PAS une erreur (cas normal : elle cible une
  classe vanilla), seulement une information neutre.
- **`Target` pointe vers une liste/table existante (18c)** : vérifié
  seulement pour les sections dont la structure est connue avec certitude
  depuis le code source du submodule (`Progressions`, `Lists`,
  `ClassDescriptions`) ; les autres sections (`Origins`, `Backgrounds`,
  `BackgroundGoals`, `ActionResources`, `ActionResourceGroups`, `Races`,
  `Feats`, `Spells`) ne reçoivent que la vérification générique (mot-clé
  `Action`, GUIDs) — pas de validation de la valeur de `Type`/`Target` en
  tant que telle (validation contre les Stats du jeu real nécessiterait
  16b/16c, `data-extractor`, hors scope statique ici)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bg3_mod_tui.pak_reader import (
    PakArchive,
    PakReaderError,
    parse_meta_lsx_bytes,
    parse_meta_lsx_dependencies_bytes,
)

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - dépend de l'environnement d'exécution
    yaml = None  # type: ignore[assignment]

# --- Identités connues (submodule Tools/BG3-Compatibility-Framework) ---

COMMUNITY_LIBRARY_UUID = "396c5966-09b0-40a1-af3f-93a5e9ce71c0"
COMPATIBILITY_FRAMEWORK_UUID = "67fbbd53-7c7d-4cfa-9409-6d737b4d92a9"
CF_DEPENDENCY_UUIDS = {COMMUNITY_LIBRARY_UUID, COMPATIBILITY_FRAMEWORK_UUID}

PLACEHOLDER_GUID = "00000000-0000-0000-0000-000000000000"

_UUID_V4_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_UUID_GENERIC_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Noms de clé JSON/YAML dont la valeur (ou les éléments, si liste) est
# attendue comme un GUID — voir CompatibilityFrameworkConfig.example.json
# et les mods réels du submodule (CF_Oathbreaker_Removal, LegacyPatches/*) :
# "UUID"/"UUIDs" partout, "modGuid"/"subClassGuid"/"classGuid" côté Lua.
_GUID_KEY_RE = re.compile(r"(guid$|^uuid$|^uuids$)", re.IGNORECASE)

# Sections top-niveau reconnues par `ConfigLayer/_ConfigLoader.lua`
# (`SubmitData`) du submodule — une section absente de cette liste est
# ignorée par le Framework en silence (jamais appliquée).
KNOWN_JSON_TOP_SECTIONS = {
    "FileVersion",
    "Origins",
    "ClassDescriptions",
    "Progressions",
    "Feats",
    "Races",
    "Lists",
    "ActionResourceGroups",
    "Spells",
    "Backgrounds",
    "BackgroundGoals",
    "ActionResources",
}

# Mots-clés d'action reconnus par la couche JSON (`data.Action` — voir
# `ProgressionHandler.lua`/`ListHandler.lua`/etc. du submodule). `Blacklist`
# des ClassDescriptions est un booléen à part, pas une action.
KNOWN_JSON_ACTIONS = {"Insert", "Remove"}

# Fonctions réellement exposées par
# CompatibilityFramework/Mods/SubclassCompatibilityFramework/ScriptExtender/
# Lua/API/*.lua du submodule (`Api.<Nom>`) — sert à repérer un nom mal
# orthographié (ex: "AddSubclass" au lieu de "InsertSubClasses").
KNOWN_LUA_API_FUNCTIONS = {
    "InsertSubClasses",
    "RemoveSubClasses",
    "InsertClass",
    "InsertLevelOneProgression",
    "InsertSelectors",
    "InsertSelector",
    "RemoveSelectors",
    "RemoveSelector",
    "InsertStrings",
    "RemoveStrings",
    "InsertSpellStrings",
    "RemoveSpellStrings",
    "InsertPassives",
    "RemovePassives",
    "InsertPassivesForRemoval",
    "RemovePassivesForRemoval",
    "InsertBoosts",
    "RemoveBoosts",
    "InsertRequirements",
    "RemoveRequirements",
    "InsertToList",
    "RemoveFromList",
    "InheritList",
    "ExcludeFromList",
    "InsertTags",
    "RemoveTags",
    "SetBoolean",
    "SetField",
    "ClassBlacklist",
    "InsertRaceChildData",
    "RemoveRaceChildData",
    "InsertResourceToGroup",
    "RemoveResourceFromGroup",
    "RegisterEquipmentListID",
    "RegisterPassiveListIDs",
    "RegisterSpellListIDs",
    "RegisterSkillListIDs",
    "RegisterAbilityListIDs",
    "RegisterActionResourceID",
    "RegisterActionResourceGroupID",
    "RegisterFeatID",
    "RegisterProgressionID",
    "ToggleDebug",
    "ToggleWarn",
}

_SE_CONFIG_SUFFIX = "ScriptExtender/Config.json"
_CF_CONFIG_SUFFIXES = (
    "ScriptExtender/CompatibilityFrameworkConfig.json",
    "ScriptExtender/CompatibilityFrameworkConfig.yaml",
    "ScriptExtender/CompatibilityFrameworkConfig.yml",
)
_BOOTSTRAP_SUFFIXES = (
    "ScriptExtender/Lua/BootstrapServer.lua",
    "ScriptExtender/Lua/BootstrapClient.lua",
)

_LUA_API_CALL_RE = re.compile(r"Mods\.SubclassCompatibilityFramework\.Api\.(\w+)")
_LUA_GUID_ASSIGN_RE = re.compile(r'(\w*[Gg]uid)\s*=\s*"([^"]*)"')
_LUA_ISMODLOADED_RE = re.compile(r'Ext\.Mod\.IsModLoaded\(\s*"([^"]*)"\s*\)')
_YAML_GUID_LINE_RE = re.compile(r'(\w*[Gg]uid|UUID)\s*:\s*"?([0-9a-fA-F-]{8,36})"?')


@dataclass
class CompatAuditResult:
    """Rapport d'audit statique pour UN mod — voir `audit_mod`.

    `applicable=False` signifie que ce mod n'a été détecté ni avec un
    `CompatibilityFrameworkConfig.*` ni avec un appel à l'API Lua du
    Framework : il n'est simplement pas concerné par cet audit (mod sans
    injection dynamique déclarée), pas un cas d'échec."""

    mod_name: str
    mod_uuid: str | None
    applicable: bool
    ok: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # ClassDescriptions[].UUID déclarés par CE mod (classes personnalisées
    # réellement enregistrées, PAS les Progressions patchées en passant) —
    # utilisé par `_check_subclass_parent_consistency` pour la cohérence
    # inter-mods (18b), pas destiné à être consommé en dehors de ce module.
    declared_class_uuids: set[str] = field(default_factory=set, repr=False)
    # (chemin JSON, UUID cible) de chaque Progressions[].Subclasses[] —
    # même usage interne que `declared_class_uuids`.
    subclass_parent_refs: list[tuple[str, str]] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict[str, list[str]]:
        """Forme `{"ok": [...], "warnings": [...], "errors": [...]}`
        demandée pour ce rapport (même esprit que `pak_validator`/
        `mod_pipeline.check_nexus_updates`)."""
        return {"ok": list(self.ok), "warnings": list(self.warnings), "errors": list(self.errors)}


def _classify_guid(value: str) -> str:
    """Classe `value` : `"ok"` (UUID v4 valide), `"placeholder"` (GUID
    factice `00000000-...`), `"not_v4"` (format UUID générique mais pas v4 —
    version/variant inattendus) ou `"invalid"` (ni l'un ni l'autre, y
    compris chaîne vide ou reliquat de template comme
    `"your-mods-uuid-in-metalsx"`)."""
    if not value or not value.strip():
        return "invalid"
    v = value.strip()
    if v == PLACEHOLDER_GUID:
        return "placeholder"
    if _UUID_V4_RE.match(v):
        return "ok"
    if _UUID_GENERIC_RE.match(v):
        return "not_v4"
    return "invalid"


def _report_guid(label: str, value: str, ok: list[str], warnings: list[str], errors: list[str]) -> None:
    kind = _classify_guid(value)
    if kind == "ok":
        return  # silencieux : pas la peine de lister chaque GUID valide, un rapport doit rester lisible
    if kind == "placeholder":
        errors.append(f"{label} : GUID factice/exemple non remplacé ({PLACEHOLDER_GUID}).")
    elif kind == "not_v4":
        warnings.append(f"{label} : « {value} » a la forme d'un UUID mais pas au format v4 (version/variant inattendus).")
    else:
        errors.append(f"{label} : « {value} » n'est pas un GUID syntaxiquement valide.")


def _collect_guids(obj: Any, path: str = "$") -> list[tuple[str, str]]:
    """Parcourt récursivement `obj` (JSON/YAML déjà parsé) et retourne
    `[(chemin, valeur), ...]` pour chaque chaîne trouvée sous une clé dont
    le nom ressemble à un GUID (voir `_GUID_KEY_RE` — `ClassGuid`,
    `SubClassGuid`, `SpellListGuid`, `PassiveGuid`, `UUID`, `UUIDs`, etc.)."""
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_path = f"{path}.{key}"
            if _GUID_KEY_RE.search(str(key)):
                if isinstance(value, str):
                    found.append((key_path, value))
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, str):
                            found.append((f"{key_path}[{i}]", item))
            found.extend(_collect_guids(value, key_path))
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found.extend(_collect_guids(item, f"{path}[{i}]"))
    return found


def _check_actions_generic(obj: Any, path: str, errors: list[str]) -> None:
    """Vérifie récursivement que tout champ `Action` rencontré, où que ce
    soit dans le document, vaut `Insert` ou `Remove` (18c, "nommage exact
    des mots-clés d'action") — appliqué globalement, pas seulement aux
    sections dont la structure fine est connue (voir docstring du module)."""
    if isinstance(obj, dict):
        action = obj.get("Action")
        if isinstance(action, str) and action not in KNOWN_JSON_ACTIONS:
            errors.append(f"{path}.Action : mot-clé d'action inconnu « {action} » (attendu Insert/Remove).")
        for key, value in obj.items():
            _check_actions_generic(value, f"{path}.{key}", errors)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _check_actions_generic(item, f"{path}[{i}]", errors)


def _check_lists_section(lists_section: Any, warnings: list[str], errors: list[str]) -> None:
    """Vérifie la section `Lists` (structure confirmée par `ListHandler.lua`
    du submodule) : `Type` non vide requis, et au moins un de
    `Items`/`Inherit`/`Exclude` (sinon l'entrée est silencieusement ignorée
    par le Framework — `ParseAndSubmitLists` retourne sans rien faire)."""
    if not isinstance(lists_section, list):
        return
    for i, entry in enumerate(lists_section):
        if not isinstance(entry, dict):
            continue
        label = f"$.Lists[{i}]"
        if not entry.get("Type"):
            errors.append(f"{label} : champ « Type » absent ou vide (requis — voir ListHandler.lua).")
        if not (entry.get("Items") or entry.get("Inherit") or entry.get("Exclude")):
            warnings.append(
                f"{label} : ni Items, ni Inherit, ni Exclude renseigné — cette entrée est "
                "silencieusement ignorée par le Framework (ParseAndSubmitLists)."
            )


def _check_progressions_section(
    progressions: Any, warnings: list[str], subclass_parent_refs: list[tuple[str, str]]
) -> None:
    """Vérifie la section `Progressions` (structure confirmée par
    `ProgressionHandler.lua`) : signale spécifiquement le piège
    "`Action: Insert` sur une sous-classe JSON n'est jamais appliqué" — la
    voie JSON ne gère QUE `Action: Remove` pour `Subclasses[]`, tout ajout
    de sous-classe doit passer par l'API Lua `InsertSubClasses`. Alimente
    aussi `subclass_parent_refs` pour la cohérence inter-mods (18b)."""
    if not isinstance(progressions, list):
        return
    for i, prog in enumerate(progressions):
        if not isinstance(prog, dict):
            continue
        prog_uuid = prog.get("UUID")
        label = f"$.Progressions[{i}]"
        for j, subclass in enumerate(prog.get("Subclasses") or []):
            if not isinstance(subclass, dict):
                continue
            sub_label = f"{label}.Subclasses[{j}]"
            action = subclass.get("Action")
            if action != "Remove":
                warnings.append(
                    f"{sub_label} : Action « {action or '(absent)'} » — cette version du "
                    "Framework n'applique les entrées Subclasses du JSON qu'avec "
                    "Action=\"Remove\" (voir ProgressionHandler.lua) ; un ajout de "
                    "sous-classe doit passer par l'API Lua Api.InsertSubClasses, pas par "
                    "CompatibilityFrameworkConfig.json — cette entrée est probablement "
                    "silencieusement ignorée."
                )
            if isinstance(prog_uuid, str) and _classify_guid(prog_uuid) in {"ok", "not_v4"}:
                subclass_parent_refs.append((sub_label, prog_uuid))


def _guid_content_from_entry(pak: PakArchive, suffix: str) -> str | None:
    entry = pak.find_suffix(suffix)
    if entry is None:
        return None
    try:
        content = pak.read(entry)
    except PakReaderError:
        return None
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _audit_config_file(
    text: str, filename: str, ok: list[str], warnings: list[str], errors: list[str]
) -> tuple[dict | None, list[tuple[str, str]]]:
    """Parse et audite un `CompatibilityFrameworkConfig.{json,yaml,yml}` déjà
    lu en texte. Retourne `(data_parsé_ou_None, subclass_parent_refs)` —
    `data` est `None` si le fichier n'a pas pu être parsé (erreur déjà
    ajoutée à `errors`)."""
    subclass_parent_refs: list[tuple[str, str]] = []
    is_yaml = filename.endswith((".yaml", ".yml"))

    if is_yaml:
        if yaml is None:
            warnings.append(
                f"{filename} : PyYAML non installé dans cet environnement — syntaxe non "
                "vérifiée (repli sur un scan texte approximatif des GUIDs uniquement)."
            )
            for match in _YAML_GUID_LINE_RE.finditer(text):
                _report_guid(f"{filename} (scan texte, {match.group(1)})", match.group(2), ok, warnings, errors)
            return None, subclass_parent_refs
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:  # type: ignore[union-attr]
            errors.append(f"{filename} : YAML invalide — {exc}")
            return None, subclass_parent_refs
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{filename} : JSON invalide — {exc.msg} (ligne {exc.lineno}, colonne {exc.colno}).")
            return None, subclass_parent_refs

    if data is None:
        warnings.append(f"{filename} : fichier vide.")
        return None, subclass_parent_refs
    if not isinstance(data, dict):
        errors.append(f"{filename} : racine attendue de type objet (dictionnaire).")
        return None, subclass_parent_refs

    ok.append(f"{filename} : syntaxe valide.")

    unknown_sections = set(data) - KNOWN_JSON_TOP_SECTIONS
    if unknown_sections:
        warnings.append(
            f"{filename} : section(s) de premier niveau inconnue(s) « {', '.join(sorted(unknown_sections))} » "
            "— ignorée(s) en silence par le Framework (ConfigLayer/_ConfigLoader.lua)."
        )

    errors_before = len(errors)
    _check_actions_generic(data, "$", errors)

    for label, value in _collect_guids(data):
        _report_guid(f"{filename} {label}", value, ok, warnings, errors)

    if "Lists" in data:
        _check_lists_section(data["Lists"], warnings, errors)
    if "Progressions" in data:
        _check_progressions_section(data["Progressions"], warnings, subclass_parent_refs)

    if len(errors) == errors_before and not unknown_sections:
        pass  # pas de "ok" supplémentaire nécessaire, déjà couvert par "syntaxe valide"

    return data, subclass_parent_refs


def _audit_bootstrap_lua(text: str, filename: str, ok: list[str], warnings: list[str], errors: list[str]) -> bool:
    """Audite un `BootstrapServer.lua`/`BootstrapClient.lua` : appels à
    l'API Lua du Framework (nom de fonction connu ?) et GUIDs passés en
    argument (format valide ? pas un reliquat de template ?). Retourne
    `True` si au moins un appel à l'API du Framework a été trouvé (signal
    d'intégration pour 18a)."""
    api_calls = _LUA_API_CALL_RE.findall(text)
    for name in api_calls:
        if name not in KNOWN_LUA_API_FUNCTIONS:
            errors.append(
                f"{filename} : fonction d'API Compatibility Framework inconnue « {name} » "
                "— vérifie l'orthographe exacte (voir Tools/BG3-Compatibility-Framework/"
                "CompatibilityFramework/.../ScriptExtender/Lua/API/*.lua)."
            )
    for match in _LUA_GUID_ASSIGN_RE.finditer(text):
        var_name, value = match.group(1), match.group(2)
        _report_guid(f"{filename} ({var_name})", value, ok, warnings, errors)
    for match in _LUA_ISMODLOADED_RE.finditer(text):
        _report_guid(f"{filename} (Ext.Mod.IsModLoaded)", match.group(1), ok, warnings, errors)
    if api_calls:
        ok.append(f"{filename} : {len(api_calls)} appel(s) à l'API Compatibility Framework trouvé(s).")
    return bool(api_calls)


def audit_mod(pak_path: Path) -> CompatAuditResult:
    """Audite statiquement UN .pak déployé pour les sous-tâches 18a-18c du
    TODO. Ne lève jamais d'exception pour un .pak illisible/corrompu
    nativement : le résultat porte l'erreur (`applicable=True`,
    `errors=["..."]`) plutôt que de faire échouer tout l'audit — même
    principe que `pak_validator.validate_pak`.

    Un mod qui ne déclare NI `CompatibilityFrameworkConfig.*` NI d'appel à
    l'API Lua du Framework retourne `applicable=False` (mod hors scope,
    pas un cas d'échec — la plupart des mods installés ne sont pas
    concernés par le Compatibility Framework)."""
    mod_name = pak_path.stem
    ok: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    declared_class_uuids: set[str] = set()
    subclass_parent_refs: list[tuple[str, str]] = []

    try:
        with PakArchive.open(pak_path) as pak:
            meta_entry = pak.find_suffix("meta.lsx")
            mod_uuid: str | None = None
            dependencies: list[tuple[str, str]] = []
            if meta_entry is not None:
                try:
                    meta_bytes = pak.read(meta_entry)
                except PakReaderError as exc:
                    errors.append(f"meta.lsx illisible : {exc}")
                    meta_bytes = None
                if meta_bytes is not None:
                    identity = parse_meta_lsx_bytes(meta_bytes)
                    if identity is not None:
                        mod_uuid, name, _folder = identity
                        mod_name = name or mod_name
                    dependencies = parse_meta_lsx_dependencies_bytes(meta_bytes)

            has_se_config = pak.find_suffix(_SE_CONFIG_SUFFIX) is not None

            cf_config_texts: list[tuple[str, str]] = []
            for suffix in _CF_CONFIG_SUFFIXES:
                text = _guid_content_from_entry(pak, suffix)
                if text is not None:
                    cf_config_texts.append((Path(suffix).name, text))

            bootstrap_texts: list[tuple[str, str]] = []
            for suffix in _BOOTSTRAP_SUFFIXES:
                text = _guid_content_from_entry(pak, suffix)
                if text is not None:
                    bootstrap_texts.append((Path(suffix).name, text))
    except PakReaderError as exc:
        return CompatAuditResult(
            mod_name=mod_name, mod_uuid=None, applicable=True, errors=[f".pak illisible nativement : {exc}"]
        )

    has_cf_json = bool(cf_config_texts)
    has_cf_lua_api = False

    # 18c/18b sur chaque BootstrapServer/Client.lua trouvé — fait AVANT de
    # décider `applicable` : un mod purement Lua (pas de config JSON) doit
    # quand même être détecté via ses appels API.
    for filename, text in bootstrap_texts:
        if _audit_bootstrap_lua(text, filename, ok, warnings, errors):
            has_cf_lua_api = True

    applicable = has_cf_json or has_cf_lua_api
    if not applicable:
        return CompatAuditResult(
            mod_name=mod_name,
            mod_uuid=mod_uuid,
            applicable=False,
            ok=["Aucune intégration Compatibility Framework détectée — mod hors scope de cet audit."],
        )

    # 18a : dépendances déclarées
    if not has_se_config:
        errors.append(
            f"{_SE_CONFIG_SUFFIX} absent : le Script Extender n'est pas déclaré comme requis "
            "pour ce mod, alors qu'il utilise le Compatibility Framework."
        )
    else:
        ok.append("Dépendance Script Extender déclarée (ScriptExtender/Config.json présent).")

    dep_uuids = {u for u, _ in dependencies}
    if dep_uuids & CF_DEPENDENCY_UUIDS:
        ok.append("Dépendance meta.lsx vers CommunityLibrary/CompatibilityFramework déclarée.")
    else:
        warnings.append(
            "Aucune dépendance meta.lsx vers CommunityLibrary "
            f"({COMMUNITY_LIBRARY_UUID}) ni CompatibilityFramework ({COMPATIBILITY_FRAMEWORK_UUID}) "
            "— le Framework découvre CompatibilityFrameworkConfig.* automatiquement sans "
            "dépendance explicite, mais la déclarer reste la bonne pratique."
        )

    # 18a/18b/18c sur chaque CompatibilityFrameworkConfig.* trouvé
    for filename, text in cf_config_texts:
        data, refs = _audit_config_file(text, filename, ok, warnings, errors)
        subclass_parent_refs.extend(refs)
        if isinstance(data, dict):
            # Volontairement SEULEMENT `ClassDescriptions` : une entrée
            # `Progressions[].UUID` ne signifie PAS que ce mod "possède"
            # cette classe — n'importe quel mod peut patcher une
            # Progression (vanilla ou non) pour y retirer/insérer un
            # élément. Seule une entrée `ClassDescriptions` déclare
            # réellement une classe personnalisée (voir
            # `ClassDescriptionHandler.lua` du submodule).
            for entry in data.get("ClassDescriptions") or []:
                if isinstance(entry, dict):
                    uuid_val = entry.get("UUID")
                    if isinstance(uuid_val, str) and _classify_guid(uuid_val) in {"ok", "not_v4"}:
                        declared_class_uuids.add(uuid_val)

    if not has_cf_json and has_cf_lua_api:
        ok.append(
            "Intégration purement via API Lua (pas de CompatibilityFrameworkConfig.json/.yaml) "
            "— 18a/18b/18c vérifiés sur BootstrapServer.lua/BootstrapClient.lua uniquement."
        )

    return CompatAuditResult(
        mod_name=mod_name,
        mod_uuid=mod_uuid,
        applicable=True,
        ok=ok,
        warnings=warnings,
        errors=errors,
        declared_class_uuids=declared_class_uuids,
        subclass_parent_refs=subclass_parent_refs,
    )


def _check_subclass_parent_consistency(results: list[CompatAuditResult]) -> None:
    """Complète chaque résultat `applicable` avec une note de cohérence
    inter-mods (18b, repli documenté dans le module) : pour chaque
    `Progressions[].Subclasses[]` trouvé, la Progression englobante
    (`ParentGuid` implicite) est-elle déclarée comme classe personnalisée
    par un des mods scannés (`ClassDescriptions[].UUID`) ? Si non, c'est le
    cas normal (cible une classe vanilla) : simple note, PAS une erreur —
    aucun référentiel des GUIDs vanilla n'existe dans ce dépôt."""
    all_declared: set[str] = set()
    for result in results:
        all_declared |= result.declared_class_uuids

    for result in results:
        for label, parent_uuid in result.subclass_parent_refs:
            if parent_uuid in all_declared:
                result.ok.append(
                    f"{label} : Progression parente ({parent_uuid}) déclarée par un mod "
                    "personnalisé scanné — cohérence interne confirmée."
                )
            else:
                result.warnings.append(
                    f"{label} : Progression parente ({parent_uuid}) non déclarée par un mod "
                    "personnalisé scanné — probablement une classe vanilla (pas vérifiable, "
                    "aucun référentiel des GUIDs vanilla dans ce dépôt ; voir TODO 18b)."
                )


def audit_installed_mods(pak_paths: list[Path]) -> list[CompatAuditResult]:
    """Audite tous les `.pak` de `pak_paths` (typiquement `Mods/*.pak` du
    profil actif — voir `screens/actions.py`) et retourne un
    `CompatAuditResult` par mod, y compris les mods non concernés
    (`applicable=False`, filtrés côté appelant si besoin — voir
    `write_compat_audit_report`). Deux passes : audit individuel de chaque
    mod, puis cohérence inter-mods des références de sous-classes
    (`_check_subclass_parent_consistency`, 18b)."""
    results = [audit_mod(path) for path in pak_paths]
    _check_subclass_parent_consistency([r for r in results if r.applicable])
    return results


def write_compat_audit_markdown(results: list[CompatAuditResult]) -> str:
    """Formate `results` (voir `audit_installed_mods`) en Markdown, dans le
    même esprit que `pak_validation.md`/`mod_dependencies.md` déjà produits
    par ce projet — un fichier prêt à écrire tel quel, l'écriture disque
    reste à la charge de l'appelant (voir `screens/actions.py`)."""
    applicable = [r for r in results if r.applicable]
    total = len(results)
    with_errors = [r for r in applicable if r.errors]
    with_warnings_only = [r for r in applicable if r.warnings and not r.errors]
    clean = [r for r in applicable if not r.errors and not r.warnings]

    lines = ["# Audit de compatibilité (BG3 Compatibility Framework)\n"]
    lines.append(
        "Vérification STATIQUE (18a-18c du TODO section 18) : fichiers de config et "
        "dépendances, syntaxe des GUIDs, déclarations d'injection. **Ne remplace pas** "
        "un test en jeu (18d, manuel — logs Script Extender au chargement + validation "
        "visuelle en jeu) — voir `compat_audit.py` pour les limites détaillées.\n"
    )
    lines.append(
        f"{len(applicable)} mod(s) concerné(s) par le Compatibility Framework sur {total} "
        f"scanné(s) — {len(with_errors)} avec erreur(s), {len(with_warnings_only)} avec "
        f"avertissement(s) seulement, {len(clean)} sans problème détecté.\n"
    )

    for result in sorted(applicable, key=lambda r: r.mod_name.lower()):
        lines.append(f"## {result.mod_name}\n")
        if result.mod_uuid:
            lines.append(f"UUID : `{result.mod_uuid}`\n")
        if result.errors:
            lines.append("**Erreurs :**\n")
            for msg in result.errors:
                lines.append(f"- {msg}")
            lines.append("")
        if result.warnings:
            lines.append("**Avertissements :**\n")
            for msg in result.warnings:
                lines.append(f"- {msg}")
            lines.append("")
        if result.ok:
            lines.append("**OK :**\n")
            for msg in result.ok:
                lines.append(f"- {msg}")
            lines.append("")

    not_applicable = total - len(applicable)
    if not_applicable:
        lines.append(
            f"({not_applicable} autre(s) mod(s) scanné(s) sans intégration Compatibility "
            "Framework détectée — non listé(s) ci-dessus.)\n"
        )

    return "\n".join(lines) + "\n"
