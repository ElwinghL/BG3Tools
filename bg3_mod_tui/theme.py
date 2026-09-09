"""Thème visuel du TUI, aux couleurs de Baldur's Gate 3 (bronze/or patiné
sur fond anthracite, plutôt que le bleu par défaut de Textual).

Un `Theme` Textual ne fixe que les dix couleurs de base ; toutes les
variables dérivées utilisées par les widgets (`$primary-darken-2`,
`$success-muted`, `$text-success`, ...) sont recalculées automatiquement
à partir de celles-ci par `ColorSystem` — inutile de les redéfinir une
par une dans chaque écran.

La palette source ne fournissait pas de teinte dédiée "avertissement" ni
"succès" : l'or (`$primary`, déjà utilisé pour les titres) fait office
d'avertissement, et le bleu sarcelle (magie/esprit) de succès — voir les
commentaires ci-dessous pour le mapping complet."""

from __future__ import annotations

from textual.theme import Theme

BG3_THEME = Theme(
    name="bg3",
    # Or Lumineux — titres, boutons primaires, focus.
    primary="#C5A059",
    # Bleu Sarcelle (magie/esprit) — accents secondaires ; fait aussi
    # office de "succès" en l'absence de vert dédié dans la palette.
    secondary="#4D7C8A",
    success="#4D7C8A",
    # Or Lumineux réutilisé comme "avertissement" (pas de teinte dédiée
    # fournie) — reste distinct du rouge (erreur) et du bronze (bordures).
    warning="#C5A059",
    # Rouge Sombre (surbrillance/santé) — erreurs.
    error="#A62626",
    # Bronze / Or Patiné — bordures et cadres (`border: round $accent`,
    # omniprésent dans les écrans du TUI).
    accent="#8C7853",
    # Ivoire / Blanc Cassé — texte standard.
    foreground="#EAE6DF",
    # Noir Profond / Anthracite — fond principal.
    background="#0B0C10",
    # Brun / Gris chaud sombre — panneaux et menus.
    surface="#1A1813",
    # Variante un peu plus clair que `surface`, pour distinguer les
    # panneaux secondaires (ex: console outils) — pas fournie par la
    # palette source, choisie par cohérence avec elle.
    panel="#241F17",
    dark=True,
)
