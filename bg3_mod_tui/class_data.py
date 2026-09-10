"""Données de classes/sous-classes pour le planificateur de build (TODO P3.10).

Portée et limites (à lire avant de faire confiance aveuglément aux données) :

- Les 12 classes de base de Baldur's Gate 3 sont couvertes (Barbare, Barde,
  Clerc, Druide, Guerrier, Moine, Paladin, Rôdeur, Roublard, Ensorceleur,
  Occultiste, Magicien), avec leurs sous-classes principales connues du jeu
  (édition définitive / derniers patchs au moment de l'écriture).
- BG3 plafonne réellement les personnages au niveau 12. Ce planificateur
  modélise volontairement la plage complète **1 → 20** de D&D 5e (comme
  demandé dans le TODO), utile pour des mods qui repoussent le niveau max ou
  pour une planification "pure 5e". Les niveaux 13-20 sont donc en partie
  extrapolés depuis le SRD 5e plutôt qu'observés en jeu.
- Les gains listés par niveau (`features_by_level`) ne sont **pas garantis
  exhaustifs ni patch-exacts** : ils reflètent une bonne approximation des
  mécaniques 5e/BG3 connues, avec une entrée générique de repli
  (`GENERIC_FEATURE_FALLBACK`) pour les niveaux non détaillés. Aucune requête
  réseau n'a été faite pour les vérifier (contrainte "autonome" du TODO) —
  à corriger/compléter au besoin, la structure est prévue pour ça.
- Sources : connaissance générale du SRD D&D 5e (règles de progression,
  paliers d'amélioration de caractéristique, attaques supplémentaires) et de
  la liste des classes/sous-classes telle que présentée dans BG3, sans accès
  à une base de données externe depuis cet environnement.

Structure :

    CLASSES: dict[str, ClassInfo]
        "Fighter": {
            "fr": "Guerrier",
            "subclass_unlock_level": 3,
            "asi_levels": {4, 6, 8, 12, 14, 16, 19},
            "features_by_level": {1: [...], 2: [...], ...},
            "subclasses": {
                "Battle Master": {
                    "fr": "Maître de guerre",
                    "features_by_level": {3: [...], ...},
                },
                ...
            },
        }

`get_level_features(class_name, level, subclass_name=None)` combine les
gains de classe + sous-classe pour un niveau donné, avec repli générique.
"""

from __future__ import annotations

# Paliers standards d'amélioration de caractéristique (ASI) en 5e/BG3.
_STANDARD_ASI_LEVELS = {4, 8, 12, 16, 19}

GENERIC_FEATURE_FALLBACK = (
    "Progression de classe (sorts, ressources ou capacités supplémentaires "
    "selon la classe — non détaillé, voir la documentation 5e/BG3 pour ce "
    "niveau précis)"
)

_ASI_FEATURE = "Amélioration de caractéristique (+2 ou +1/+1) ou Don"


CLASSES: dict[str, dict] = {
    "Barbarian": {
        "fr": "Barbare",
        "subclass_unlock_level": 3,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Rage", "Défense sans armure"],
            2: ["Attaque téméraire", "Ruée sauvage"],
            3: ["Choix de voie (sous-classe)"],
            5: ["Attaque supplémentaire", "Déplacement accru"],
            7: ["Instinct féroce"],
            9: ["Critique brutal (1 dé supplémentaire)"],
            11: ["Rage implacable"],
            15: ["Rage indomptable"],
            18: ["Force indomptable"],
            20: ["Champion primitif (capstone)"],
        },
        "subclasses": {
            "Berserker": {
                "fr": "Voie du Berserker",
                "features_by_level": {
                    3: ["Furie sans limite"],
                    6: ["Emprise de la rage"],
                    10: ["Retribution intimidante"],
                    14: ["Frénésie destructrice"],
                },
            },
            "Wildheart": {
                "fr": "Voie du Cœur sauvage (esprit animal)",
                "features_by_level": {
                    3: ["Esprit animal (Aigle/Ours/Loup/Taureau/Tigre selon choix)"],
                    6: ["Aspect de l'esprit animal"],
                    10: ["Marche de l'esprit"],
                    14: ["Résurgence de l'esprit"],
                },
            },
            "Wrecker": {
                "fr": "Voie du Briseur (ajout tardif, à vérifier)",
                "features_by_level": {
                    3: ["Bonus d'arme improvisée / dégâts d'objets accrus (à confirmer)"],
                },
            },
        },
    },
    "Bard": {
        "fr": "Barde",
        "subclass_unlock_level": 3,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Sorts de barde", "Inspiration bardique"],
            2: ["Toucher-à-tout", "Chant de repos"],
            3: ["Choix de collège (sous-classe)", "Sorts supplémentaires (2ᵉ cercle)"],
            5: ["Inspiration bardique améliorée", "Sorts de 3ᵉ cercle"],
            6: ["Contre-sort et contre-capacité"],
            9: ["Sorts de 5ᵉ cercle"],
            10: ["Toucher-à-tout amélioré", "Inspiration magique"],
            14: ["Sorts de 7ᵉ cercle"],
            18: ["Toucher-à-tout suprême"],
            20: ["Chef d'orchestre suprême (capstone)"],
        },
        "subclasses": {
            "Lore": {
                "fr": "Collège du Savoir",
                "features_by_level": {
                    3: ["Savoirs supplémentaires", "Mot cinglant"],
                    6: ["Capacité magique volée"],
                },
            },
            "Valour": {
                "fr": "Collège de la Vaillance",
                "features_by_level": {
                    3: ["Maîtrise d'armes de guerre et d'armures", "Inspiration au combat"],
                    6: ["Attaque supplémentaire"],
                },
            },
        },
    },
    "Cleric": {
        "fr": "Clerc",
        "subclass_unlock_level": 1,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Sorts de clerc", "Choix de domaine divin (sous-classe dès le niveau 1)"],
            2: ["Aptitude de canalisation divine"],
            5: ["Destruction des morts-vivants"],
            10: ["Intervention divine"],
            20: ["Intervention divine améliorée (capstone)"],
        },
        "subclasses": {
            "Life": {
                "fr": "Domaine de la Vie",
                "features_by_level": {1: ["Disciple de la vie", "Sorts de domaine supplémentaires"]},
            },
            "Light": {
                "fr": "Domaine de la Lumière",
                "features_by_level": {1: ["Éclat en réserve"]},
            },
            "Trickery": {
                "fr": "Domaine de la Tromperie",
                "features_by_level": {1: ["Bénédiction de l'illusionniste"]},
            },
            "War": {
                "fr": "Domaine de la Guerre",
                "features_by_level": {1: ["Prêtre-guerrier"]},
            },
            "Knowledge": {
                "fr": "Domaine de la Connaissance",
                "features_by_level": {1: ["Bénédictions de la connaissance"]},
            },
            "Nature": {
                "fr": "Domaine de la Nature",
                "features_by_level": {1: ["Initié de la nature"]},
            },
            "Tempest": {
                "fr": "Domaine de la Tempête",
                "features_by_level": {1: ["Châtiment de la tempête"]},
            },
        },
    },
    "Druid": {
        "fr": "Druide",
        "subclass_unlock_level": 2,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Sorts de druide", "Druidique (langue)"],
            2: ["Forme sauvage", "Choix de cercle (sous-classe)"],
            18: ["Formes sauvages illimitées"],
            20: ["Archidruide (capstone)"],
        },
        "subclasses": {
            "Land": {
                "fr": "Cercle de la Terre",
                "features_by_level": {2: ["Sorts de cercle liés au terrain", "Récupération naturelle"]},
            },
            "Moon": {
                "fr": "Cercle de la Lune",
                "features_by_level": {2: ["Formes sauvages de combat améliorées"]},
            },
            "Spores": {
                "fr": "Cercle des Spores",
                "features_by_level": {2: ["Halo de spores symbiotiques", "Serviteur putrescent"]},
            },
        },
    },
    "Fighter": {
        "fr": "Guerrier",
        "subclass_unlock_level": 3,
        "asi_levels": {4, 6, 8, 12, 14, 16, 19},
        "features_by_level": {
            1: ["Style de combat", "Récupération (Second Souffle)"],
            2: ["Sursaut d'action"],
            3: ["Choix d'archétype martial (sous-classe)"],
            5: ["Attaque supplémentaire (x2)"],
            9: ["Indomptable"],
            11: ["Attaques multiples (x3)"],
            20: ["Attaques multiples (x4, capstone)"],
        },
        "subclasses": {
            "Battle Master": {
                "fr": "Maître de guerre",
                "features_by_level": {
                    3: ["Manœuvres de combat", "Dés de supériorité", "Étude du combattant"],
                    7: ["Connaissance du champ de bataille"],
                },
            },
            "Champion": {
                "fr": "Champion",
                "features_by_level": {
                    3: ["Critique amélioré (19-20)"],
                    7: ["Athlète hors pair"],
                },
            },
            "Eldritch Knight": {
                "fr": "Chevalier occulte",
                "features_by_level": {
                    3: ["Sorts de magicien (école d'évocation/abjuration)", "Lien d'arme"],
                    7: ["Riposte magique"],
                },
            },
        },
    },
    "Monk": {
        "fr": "Moine",
        "subclass_unlock_level": 3,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Défense sans armure", "Arts martiaux"],
            2: ["Ki", "Déplacement sans armure"],
            3: ["Choix de tradition monastique (sous-classe)", "Défense élusive"],
            4: ["Chute lente"],
            5: ["Attaque supplémentaire", "Paume qui étourdit"],
            6: ["Frappes ki renforcées"],
            7: ["Évasion", "Perfection passive"],
            10: ["Purification du corps"],
            14: ["Âme de diamant"],
            18: ["Corps vide (invisibilité)"],
            20: ["Corps parfait (capstone)"],
        },
        "subclasses": {
            "Open Hand": {
                "fr": "Voie de la Paume",
                "features_by_level": {3: ["Techniques de la Paume ouverte"]},
            },
            "Shadow": {
                "fr": "Voie de l'Ombre",
                "features_by_level": {3: ["Arts de l'ombre", "Pas dans les ténèbres"]},
            },
            "Four Elements": {
                "fr": "Voie des Quatre Éléments",
                "features_by_level": {3: ["Disciplines élémentaires"]},
            },
        },
    },
    "Paladin": {
        "fr": "Paladin",
        "subclass_unlock_level": 3,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Sens divin", "Soin aux mains (Rétablissement)"],
            2: ["Châtiment divin", "Sorts de paladin", "Style de combat"],
            3: ["Choix de serment sacré (sous-classe)", "Résistance divine"],
            5: ["Attaque supplémentaire"],
            6: ["Aura de protection"],
            10: ["Aura de courage"],
            11: ["Arme sacrée renforcée"],
            14: ["Toucher purificateur"],
            20: ["Capstone de serment"],
        },
        "subclasses": {
            "Devotion": {
                "fr": "Serment de Dévotion",
                "features_by_level": {3: ["Châtiment sacré", "Sens du mal et du bien"]},
            },
            "Ancients": {
                "fr": "Serment des Anciens",
                "features_by_level": {3: ["Flamme de la vengeance protectrice", "Sens du mal et du bien"]},
            },
            "Vengeance": {
                "fr": "Serment de Vengeance",
                "features_by_level": {3: ["Ennemi juré", "Pas vengeur"]},
            },
        },
    },
    "Ranger": {
        "fr": "Rôdeur",
        "subclass_unlock_level": 3,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Ennemi juré / Explorateur émérite", "Style de combat"],
            2: ["Sorts de rôdeur"],
            3: ["Choix d'archétype (sous-classe)", "Style de combat primitif"],
            5: ["Attaque supplémentaire"],
            8: ["Pas du prédateur"],
            10: ["Cache-cache naturel"],
            14: ["Disparition"],
            20: ["Chasseur suprême (capstone)"],
        },
        "subclasses": {
            "Beast Master": {
                "fr": "Maître des bêtes",
                "features_by_level": {3: ["Compagnon animal"]},
            },
            "Hunter": {
                "fr": "Chasseur",
                "features_by_level": {3: ["Aptitude de chasseur (au choix)"]},
            },
            "Gloom Stalker": {
                "fr": "Traqueur des ténèbres",
                "features_by_level": {3: ["Vision dans le noir renforcée", "Embuscade des ténèbres"]},
            },
        },
    },
    "Rogue": {
        "fr": "Roublard",
        "subclass_unlock_level": 3,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Maîtrise des outils", "Attaque sournoise (1d6)", "Argot des voleurs"],
            2: ["Action rusée"],
            3: ["Choix d'archétype roublard (sous-classe)"],
            5: ["Esquive totale"],
            7: ["Sens aiguisés (évasion)"],
            11: ["Fiabilité (Reliable Talent)"],
            14: ["Perception aveugle"],
            15: ["Bluff insaisissable"],
            18: ["Élusif (Elusive)"],
            20: ["Coup de chance (capstone)"],
        },
        "subclasses": {
            "Thief": {
                "fr": "Voleur",
                "features_by_level": {3: ["Doigts agiles supplémentaires", "Escalade rapide"]},
            },
            "Assassin": {
                "fr": "Assassin",
                "features_by_level": {3: ["Maîtrise des déguisements", "Attaque sournoise garantie en surprise"]},
            },
            "Arcane Trickster": {
                "fr": "Filou arcanique",
                "features_by_level": {3: ["Sorts de magicien (école d'illusion/enchantement)", "Ruse magique"]},
            },
        },
    },
    "Sorcerer": {
        "fr": "Ensorceleur",
        "subclass_unlock_level": 1,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Sorts d'ensorceleur", "Choix d'origine magique (sous-classe dès le niveau 1)"],
            2: ["Métamagie (2 options)"],
            3: ["Métamagie (options supplémentaires accessibles)"],
            20: ["Restauration de sorcellerie (capstone)"],
        },
        "subclasses": {
            "Draconic Bloodline": {
                "fr": "Lignée draconique",
                "features_by_level": {1: ["Résilience draconique", "Ascendance draconique"]},
            },
            "Wild Magic": {
                "fr": "Magie sauvage",
                "features_by_level": {1: ["Surtension de magie sauvage", "Chance ensorcelée"]},
            },
            "Storm": {
                "fr": "Sorcellerie de la Tempête (ajout tardif, à vérifier)",
                "features_by_level": {1: ["Vol de tempête (à confirmer)"]},
            },
        },
    },
    "Warlock": {
        "fr": "Occultiste",
        "subclass_unlock_level": 1,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Sorts d'occultiste (Pacte magique)", "Choix de protecteur (sous-classe dès le niveau 1)"],
            2: ["Invocations occultes"],
            3: ["Choix de pacte (Lame/Chaîne/Tome)"],
            11: ["Arcanes mystiques"],
            20: ["Maître occulte (capstone)"],
        },
        "subclasses": {
            "Fiend": {
                "fr": "Le Fiélon",
                "features_by_level": {1: ["Résilience noire"]},
            },
            "Archfey": {
                "fr": "L'Archifée",
                "features_by_level": {1: ["Présence féérique"]},
            },
            "Great Old One": {
                "fr": "Le Grand Ancien",
                "features_by_level": {1: ["Sonde mentale"]},
            },
        },
    },
    "Wizard": {
        "fr": "Magicien",
        "subclass_unlock_level": 2,
        "asi_levels": _STANDARD_ASI_LEVELS,
        "features_by_level": {
            1: ["Sorts de magicien", "Récupération arcanique"],
            2: ["Choix d'école de magie (sous-classe)"],
            18: ["Maîtrise des sorts"],
            20: ["Signature spectrale (capstone)"],
        },
        "subclasses": {
            "Evocation": {"fr": "École d'Évocation", "features_by_level": {2: ["Sculpteur de sorts"]}},
            "Abjuration": {"fr": "École d'Abjuration", "features_by_level": {2: ["Bouclier arcanique"]}},
            "Conjuration": {"fr": "École de Conjuration", "features_by_level": {2: ["Invocation mineure"]}},
            "Divination": {"fr": "École de Divination", "features_by_level": {2: ["Présage"]}},
            "Enchantment": {"fr": "École d'Enchantement", "features_by_level": {2: ["Charme instinctif"]}},
            "Illusion": {"fr": "École d'Illusion", "features_by_level": {2: ["Illusion améliorée"]}},
            "Necromancy": {"fr": "École de Nécromancie", "features_by_level": {2: ["Robustesse macabre"]}},
            "Transmutation": {"fr": "École de Transmutation", "features_by_level": {2: ["Pierre de transmutation"]}},
        },
    },
}


def class_names() -> list[str]:
    """Noms internes (clés `CLASSES`) triés alphabétiquement (stable pour l'UI)."""
    return sorted(CLASSES)


def get_level_features(class_name: str, level: int, subclass_name: str | None = None) -> list[str]:
    """Retourne la liste des gains affichés pour `class_name` à `level`,
    en combinant les gains de classe, les gains de sous-classe (si
    `subclass_name` est fourni et débloquée) et un palier générique
    d'amélioration de caractéristique le cas échéant. Repli générique
    (`GENERIC_FEATURE_FALLBACK`) si rien de spécifique n'est documenté."""
    info = CLASSES.get(class_name)
    if info is None:
        return [GENERIC_FEATURE_FALLBACK]

    features: list[str] = list(info["features_by_level"].get(level, []))

    if level in info.get("asi_levels", set()) and not any("Amélioration" in f for f in features):
        features.append(_ASI_FEATURE)

    if subclass_name:
        subclass = info["subclasses"].get(subclass_name)
        if subclass is not None:
            unlock = info["subclass_unlock_level"]
            if level == unlock:
                features.append(f"Choix de sous-classe : {subclass['fr']}")
            features.extend(subclass["features_by_level"].get(level, []))

    if not features:
        features.append(GENERIC_FEATURE_FALLBACK)

    return features
