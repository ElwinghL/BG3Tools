"""Résolution de l'origine (Nexus/mod.io) des .pak "isolés" : des .pak
glissés-déposés directement dans Mods/ (ou par un autre mod manager) sans
passer par aucune archive connue de ce TUI — `inventory.PakEntry.
matched_archive` (et donc `inventory.build_inventory()["paks"][i]
["matched_archive"]`) reste alors vide pour eux, faute d'archive de
`archives_dir`/`_installees`/`_a_traiter` partageant leur nom.

Trois mécanismes de résolution, tentés dans cet ordre (fiabilité
croissante) — voir `screens/actions.py` pour leur enchaînement :
1. `match_orphan_by_name` — heuristique par nom, la moins fiable.
2. `match_orphan_by_uuid` — certaine, via l'UUID réel du `meta.lsx` (voir
   `pak_metadata`) plutôt qu'un hash de fichier brut, qui varierait selon
   la compression/le repackaging d'une archive alors que le mod est
   identique — contrairement à l'UUID du `ModuleInfo`, que BG3 lui-même
   utilise pour identifier un mod.
3. Si les deux précédents échouent : demande à l'utilisateur d'indiquer un
   lien Nexus/mod.io (`parse_manual_origin_link`), mémorisé ensuite pour
   ne plus être redemandé aux scans suivants (`load_manual_origins`/
   `save_manual_origin`)."""

from __future__ import annotations

from pathlib import Path

from bg3_mod_tui.inventory import ArchiveEntry, match_archive_origin


def find_orphaned_paks(paks: list[dict]) -> list[dict]:
    """.pak de `inventory.build_inventory()["paks"]` (liste de dicts, voir
    `inventory.PakEntry`) sans archive associée (`matched_archive` vide) —
    candidats à une résolution d'origine par ce module (glisser-déposer
    direct dans Mods/, hors circuit Nexus/mod.io de ce TUI)."""
    return [p for p in paks if not p.get("matched_archive")]


def match_orphan_by_name(pak_file: str, archives: list[ArchiveEntry]) -> dict | None:
    """Étape 1 (heuristique, la moins fiable) : tente de relier `pak_file`
    (nom de fichier complet d'un .pak isolé) à l'une des archives locales
    déjà connues (`archives_dir`/`_installees`/`_a_traiter`, voir
    `inventory.scan_all_archives`) par similarité de nom — réutilise
    `inventory.match_archive_origin` (même logique que l'association déjà
    faite par `build_inventory`, ici appliquée explicitement à un .pak
    isolé en particulier).

    Ne prouve rien : deux mods différents peuvent avoir un nom proche, et
    un .pak véritablement téléchargé hors de ce TUI (aucune archive locale
    du tout) ne trouvera jamais de correspondance ici — dans ce cas,
    tenter `match_orphan_by_uuid` (fiable), puis en dernier recours la
    saisie manuelle (`parse_manual_origin_link`)."""
    stem = Path(pak_file).stem
    return match_archive_origin(stem, archives)
