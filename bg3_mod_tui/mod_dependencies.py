"""Vérification des dépendances déclarées par les mods déployés (nœud
`Dependencies` de chaque `meta.lsx`, voir `pak_metadata.ModuleMetadata`)
contre l'ensemble des mods effectivement présents sous `Mods/` — signale
toute dépendance dont l'UUID ne correspond à AUCUN .pak déployé, ce qui
indique un prérequis manquant (mod requis non installé, ou pas encore
extrait vers `Mods/`).

Volontairement SANS détection d'incompatibilités : contrairement aux
dépendances, BG3 n'a pas de champ structuré "incompatible avec" dans
`meta.lsx` — cette information n'existe qu'en texte libre sur la page
Nexus de chaque mod, et la récupérer demanderait de scraper le HTML de
chaque page (fragile, pas dans l'API publique Nexus, limite de mods à
vérifier douteuse côté ToS) — décision explicite d'Elwingh de s'en tenir
aux dépendances, extractibles de façon fiable depuis les .pak eux-mêmes."""

from __future__ import annotations

from bg3_mod_tui.pak_metadata import ModuleMetadata

# Modules "système" livrés avec le jeu lui-même (jamais un vrai .pak sous
# Mods/) : une dépendance qui pointe vers l'un d'eux n'est donc jamais
# "manquante" au sens où on l'entend ici. Repris tel quel du catalogue
# déjà maintenu par Tools/BG3-Load-Order-Optimizer/src/Nemix.BG3LoadOptimizer.BG3/
# Bg3SystemModules.cs (`IsBuiltIn`) plutôt que redérivé/deviné : mêmes
# UUID (seuls GustavDev/GustavX y sont vérifiés) et mêmes noms de repli
# pour les modules sans UUID confirmé (Gustav, Shared, SharedDev, SharedX,
# Honour, HonourX).
VANILLA_MODULE_UUIDS = {
    "28ac9ce2-2aba-8cda-b3b5-6e922f71b6b8",  # GustavDev
    "cb555efe-2d9e-131f-8195-a89329d218ea",  # GustavX
}
VANILLA_MODULE_NAMES = {
    "gustav",
    "gustavdev",
    "gustavx",
    "shared",
    "shareddev",
    "sharedx",
    "honour",
    "honourx",
}


def find_missing_dependencies(
    mods: dict[str, ModuleMetadata],
) -> dict[str, list[tuple[str, str]]]:
    """Pour chaque mod de `mods` (UUID -> `ModuleMetadata`, typiquement
    `pak_metadata.build_module_metadata_index` sur tous les .pak de
    `Mods/`), retourne les dépendances déclarées dont l'UUID ne
    correspond ni à un autre mod de `mods` ni à un module vanilla connu
    (voir `VANILLA_MODULE_UUIDS`/`VANILLA_MODULE_NAMES`).

    Retourne `{nom_du_mod: [(uuid_manquant, nom_manquant), ...]}` — mods
    sans dépendance manquante absents du résultat. Fonction pure (aucun
    I/O), testable sans .pak réel."""
    available_uuids = set(mods) | VANILLA_MODULE_UUIDS
    missing: dict[str, list[tuple[str, str]]] = {}
    for mod in mods.values():
        gaps = [
            (dep_uuid, dep_name)
            for dep_uuid, dep_name in mod.dependencies
            if dep_uuid not in available_uuids
            and dep_name.strip().lower() not in VANILLA_MODULE_NAMES
        ]
        if gaps:
            missing[mod.name or mod.uuid] = gaps
    return missing


def count_dependency_declarations(mods: dict[str, ModuleMetadata]) -> dict[str, int]:
    """Combien de mods DIFFÉRENTS de `mods` déclarent chaque UUID comme
    dépendance — sert à distinguer, dans le rapport, une dépendance
    manquante propre à UN mod (probablement un vrai prérequis) d'une
    déclarée par presque tous les mods vérifiés (signature typique d'un
    module "système" injecté automatiquement par la chaîne d'export
    utilisée par l'auteur — BG3 Mod Manager/Divine.exe ajoutent parfois
    en bloc tous les modules connus localement au moment de l'export,
    plutôt que seulement ceux réellement utilisés — et non un vrai
    prérequis). Volontairement PAS utilisé pour filtrer automatiquement
    `find_missing_dependencies` : un seuil arbitraire masquerait un vrai
    cas où plusieurs mods dépendent légitimement du même mod manquant —
    ce compte est affiché tel quel dans le rapport pour que l'utilisateur
    juge lui-même."""
    counts: dict[str, int] = {}
    for mod in mods.values():
        for dep_uuid, _dep_name in mod.dependencies:
            counts[dep_uuid] = counts.get(dep_uuid, 0) + 1
    return counts
