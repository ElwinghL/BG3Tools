"""Planificateur de build classe/sous-classe niveau 1→20 (TODO P3.10).

Fonctionnalité volontairement **autonome** : indépendante du profil actif,
des mods installés et du reste de l'outil ModTools — voir `class_data.py`
pour les données et leurs limites documentées.

Ce module porte la logique pure (testable sans navigateur) :

- `LevelChoice` : le choix de classe/sous-classe fait à un niveau donné.
- `validate_build` : applique la règle de « progression continue vs nouveau
  choix » — on peut continuer indéfiniment la progression d'une classe déjà
  prise, mais une classe ne peut être sélectionnée comme *nouveau* choix
  qu'une seule fois sur l'ensemble du build (pas d'aller-retour entre deux
  classes déjà utilisées, cf TODO 10a/10d : « aucune classe doublon »).
- `build_report` : matérialise le build validé en une liste de gains par
  niveau (structure de données, réutilisée par `generate_html` pour la page
  exportable — voir la suite du TODO pour 10b/10c/10d).

La même règle est ré-implémentée côté JavaScript dans la page HTML générée
(`generate_html`), puisque la page doit fonctionner seule dans un
navigateur, sans dépendre de ce module Python une fois exportée. Ce module
Python reste la version canonique, testée dans `tests/test_class_builder.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from bg3_mod_tui.class_data import CLASSES, get_level_features

MIN_LEVEL = 1
MAX_LEVEL = 20


@dataclass(frozen=True)
class LevelChoice:
    """Choix fait à un niveau donné du build."""

    level: int
    class_name: str
    subclass_name: str | None = None


def validate_build(choices: list[LevelChoice]) -> list[str]:
    """Valide un build niveau par niveau et retourne la liste des erreurs
    (vide si le build est valide). Règles appliquées :

    1. Les niveaux couverts doivent former la séquence continue 1..N (pas de
       trou, pas de doublon de niveau) — N pouvant être inférieur à 20 pour
       un build en cours de construction.
    2. Classe inconnue (absente de `class_data.CLASSES`) → erreur.
    3. Sous-classe choisie avant le niveau de déblocage de la classe, ou
       sous-classe inconnue pour cette classe → erreur.
    4. Une fois une sous-classe choisie pour une classe, elle doit rester la
       même sur tous les niveaux ultérieurs de cette classe (on ne change
       pas de sous-classe en cours de route).
    5. Règle de « nouveau choix » : le passage d'un niveau à l'autre vers une
       classe différente de celle du niveau précédent est un *nouveau
       choix*. Une classe ne peut faire l'objet que d'un seul nouveau choix
       sur tout le build — une fois quittée pour une autre classe, elle ne
       peut plus être reprise (pas de doublon de classe, cf TODO 10a).
    """
    errors: list[str] = []
    if not choices:
        return errors

    by_level = {c.level: c for c in choices}
    levels = sorted(by_level)

    if len(by_level) != len(choices):
        errors.append("Niveaux en double dans le build (un seul choix par niveau).")

    expected_start = MIN_LEVEL
    if levels and levels[0] != expected_start:
        errors.append(f"Le build doit commencer au niveau {MIN_LEVEL}.")

    for expected, actual in zip(range(levels[0] if levels else MIN_LEVEL, MAX_LEVEL + 1), levels):
        if expected != actual:
            errors.append(f"Niveau {expected} manquant (séquence non continue).")
            break

    used_as_new_choice: set[str] = set()
    subclass_by_class: dict[str, str] = {}
    prev_class: str | None = None

    for level in levels:
        choice = by_level[level]
        info = CLASSES.get(choice.class_name)
        if info is None:
            errors.append(f"Niveau {level} : classe inconnue « {choice.class_name} ».")
            continue

        is_new_choice = choice.class_name != prev_class
        if is_new_choice:
            if choice.class_name in used_as_new_choice:
                errors.append(
                    f"Niveau {level} : la classe « {choice.class_name} » a déjà été "
                    "quittée plus tôt dans le build — impossible de la reprendre "
                    "comme nouveau choix (une classe ne peut être choisie qu'une "
                    "seule fois comme nouveau choix, la progression continue est "
                    "en revanche illimitée)."
                )
            used_as_new_choice.add(choice.class_name)

        if choice.subclass_name:
            if choice.subclass_name not in info["subclasses"]:
                errors.append(
                    f"Niveau {level} : sous-classe inconnue « {choice.subclass_name} » "
                    f"pour {choice.class_name}."
                )
            else:
                unlock = info["subclass_unlock_level"]
                if level < unlock:
                    errors.append(
                        f"Niveau {level} : sous-classe choisie avant le niveau de "
                        f"déblocage ({unlock}) pour {choice.class_name}."
                    )
                existing = subclass_by_class.get(choice.class_name)
                if existing is not None and existing != choice.subclass_name:
                    errors.append(
                        f"Niveau {level} : changement de sous-classe pour "
                        f"{choice.class_name} ({existing} → {choice.subclass_name}) — "
                        "la sous-classe est fixée une fois choisie."
                    )
                else:
                    subclass_by_class[choice.class_name] = choice.subclass_name

        prev_class = choice.class_name

    return errors


def build_report(choices: list[LevelChoice]) -> list[dict]:
    """Matérialise un build validé en une liste (une entrée par niveau
    trié) de : niveau, classe (interne + FR), sous-classe active à ce
    niveau le cas échéant, et gains affichés (`class_data.get_level_features`).
    N'effectue aucune validation — appeler `validate_build` avant si le
    build doit être garanti cohérent."""
    by_level = {c.level: c for c in choices}
    subclass_by_class: dict[str, str] = {}
    report: list[dict] = []

    for level in sorted(by_level):
        choice = by_level[level]
        info = CLASSES.get(choice.class_name, {})
        if choice.subclass_name:
            subclass_by_class[choice.class_name] = choice.subclass_name
        active_subclass = subclass_by_class.get(choice.class_name)

        report.append(
            {
                "level": level,
                "class_name": choice.class_name,
                "class_fr": info.get("fr", choice.class_name),
                "subclass_name": active_subclass,
                "subclass_fr": (
                    info.get("subclasses", {}).get(active_subclass, {}).get("fr")
                    if active_subclass
                    else None
                ),
                "features": get_level_features(choice.class_name, level, active_subclass),
            }
        )

    return report
