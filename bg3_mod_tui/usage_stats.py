"""Suivi de l'utilisation des boutons d'action du menu principal
(`screens/actions.py`) : un compteur persistant par profil, incrémenté à
chaque clic sur un vrai bouton d'action (id `action-*`, hors "Quitter") via
le hook générique `ActionsScreen.on_button_pressed`. Sert à calculer les
« quick actions » (voir `top_actions`) — les boutons les plus utilisés
affichés en raccourci en haut de l'écran.

Même style que le reste des fichiers de données par profil de `profiles.py`
(`profile_data_dir`, `load_*`/`save_*`, fichier absent ou corrompu = état
vide plutôt qu'une erreur) — voir notamment `load_blacklisted_files`."""

from __future__ import annotations

import json
from pathlib import Path

from bg3_mod_tui.profiles import profile_data_dir

USAGE_STATS_FILENAME = "usage_stats.json"


def load_usage_stats(profiles_dir: Path, profile_name: str) -> dict[str, int]:
    """Charge, pour le profil `profile_name`, le compteur d'utilisation
    `{bouton_id: nombre_de_clics}` — dictionnaire vide si le fichier est
    absent ou corrompu (aucun clic connu, pas une erreur)."""
    path = profile_data_dir(profiles_dir, profile_name) / USAGE_STATS_FILENAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(button_id): int(count) for button_id, count in raw.items()}


def save_usage_stats(profiles_dir: Path, profile_name: str, stats: dict[str, int]) -> None:
    dest_dir = profile_data_dir(profiles_dir, profile_name)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / USAGE_STATS_FILENAME).write_text(
        json.dumps(stats, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def increment_usage_stat(profiles_dir: Path, profile_name: str, button_id: str) -> dict[str, int]:
    """Incrémente de 1 le compteur de `button_id` pour le profil
    `profile_name` et persiste immédiatement le résultat (best-effort, un
    clic supplémentaire n'a pas besoin d'être groupé avec d'autres écritures
    — même logique que `save_blacklisted_files`/`save_profile_hardlinks`).
    Retourne le dictionnaire complet mis à jour, pour éviter un rechargement
    immédiat côté appelant (ex: recalcul des quick actions)."""
    stats = load_usage_stats(profiles_dir, profile_name)
    stats[button_id] = stats.get(button_id, 0) + 1
    save_usage_stats(profiles_dir, profile_name, stats)
    return stats


def top_actions(stats: dict[str, int], limit: int = 3) -> list[str]:
    """Retourne les `limit` ids de boutons les plus utilisés (ordre
    décroissant), en ignorant les compteurs à 0. Égalité de compteur
    départagée par ordre alphabétique de l'id pour un résultat déterministe
    (utile pour l'affichage stable des quick actions et pour les tests)."""
    ranked = sorted(stats.items(), key=lambda item: (-item[1], item[0]))
    return [button_id for button_id, count in ranked[:limit] if count > 0]
