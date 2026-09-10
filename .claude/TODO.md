# BG3Tools — Todo List

## P0 — Critique / Fondation

### 1. Lecteur natif `.pak` (remplacer Divine.exe)

- **1a.** Implémenter `pak_reader.py` : lecture mmap + parse header LSPK v16/v18 + decompression LZ4 index
- **1b.** Parser `meta.lsx` (XML) → extraction UUID + Name + Folder
- **1c.** Parser `meta.lsf` (binaire) → extraction UUID par regex sur la table de chaînes
- **1d.** Intégrer dans `inventory.py` : `_match_pak_to_archive` utilise `pak_reader` au lieu de Divine.exe
- **1e.** Fallback sur Divine.exe si échec lecture native (version inconnue / fichier corrompu)

### 2. Archives orphelines — écriture incrémentale du rapport

- **2a.** Remplacer l'appel unique `_write_orphans_report` par un flush à chaque étape de vérification
- **2b.** Format : un commit/étape = une ligne écrite dans `archives_orphelines.md` (UUID archive, statut, action)

## P1 — Haute priorité

### 4. Priorisation Nexus / Mod.io

- **4a.** Règle : si Mod.io version > Nexus version → privilégier Mod.io
- **4b.** (un)subscribe auto sur Mod.io lors du switch de source
- **4c.** Process de vérification de version entre archives locales et Nexus (compare version strings)

### 5. Téléchargements parallèles

- **5a.** Mod.io : téléchargement parallèle sans restriction (pas de rate-limit)
- **5b.** Nexus : max ~6 threads de DL concurrents
- **5c.** Console dédiée avec barres de progression par thread, sous la console principale
- **5d.** Préparation des wizards suivants pendant qu'un DL tourne (pipeline)

### 6. Utilitaire standalone de validation `.pak`

- **6a.** Port du check `divinity.exe` en Python pur (ou Rust via `fast_bg3_pak`)
- **6b.** Output : statut valid/invalid + détail des erreurs par `.pak`
- **6c.** Exclure : génération `modsettings.lsx` et lancement jeu

## P2 — Moyen terme

### 7. Vue par onglets (Tâches / Outils / Web)

- **7a.** Garder les trois consoles de base
- **7b.** Console Tâches : si une tâche tourne déjà et qu'un bouton déclenche une écriture → créer un onglet dédié au lieu d'empiler

### 8. Profils + quick actions

- **8a.** Compteur d'utilisation par bouton/outil/profil (persistant)
- **8b.** Affichage des 3 actions les plus utilisées en boutons quick-action en haut d'écran

### 9. Fusion bouton "Mise à jour outils" + "Compil Compat Framework" + "ModFixerFork"

- **9a.** Unified button lançant les trois séquences dans l'ordre avec barre de progression globale

## P3 — Annexe (avant V2/V3/V4)

### 10. Build de classes (page web autonome)

- **10a.** Générateur de build classe/sous-classe niveau 1→20 (aucune classe doublon)
- **10b.** Exportable, autonome (indépendant profil/mods)
- **10c.** Visualisation graph Mermaid intégrée
- **10d.** Affichage gains par niveau + changement de classe autorisé (progression continue)

### 11. Console extender intercepter/flux

- **11a.** Outil interceptant la console du script extender (Proton lag) → rapport dans un terminal TUI lisible
- **11b.** Transmission bidirectionnelle (lecture + écrit de commandes)
- **11c.** Auto-complétion des commandes disponibles

## P4 — Futur

### 12. Release standalone

- **12a.** Packaging wheel Python indépendant du mod
- **12b.** GUI Python cross-platform (Linux + Windows) reprenant les fonctionnalités ci-dessus
- **12c.** Alternative serveur web local : visualisation par navigateur, échange .pak/profils par socket sécurisé (clé + fichier auth type SSH)

### 13. Licence

- **13a.** Identifier et citer les licences des outils/inspirations utilisés

### 14. Convention de nommage des merges

- **14a.** Renommer les merges de branches précédents pour suivre la convention : message de commit = nom de branche

## Fait

- progression X/Y pour téléchargement depuis fichier texte
- message "déjà un hardlink" enrichi (mod, chemin)
- alignement colonne console tâches (compteur .pak extraits 2 digits)
- déduplication archives mod.io + nettoyage intégré dans `_installees`
- import profil : vérification fichiers manquants + garde-fou version
- wizard sélection ZIP imbriqués (garder/extraire)
- texte doublons supprimés codifié (fmt_row, statuts colorés)
- matching mods glisser-déposer → Nexus/Mod.io (nom, UUID meta.lsx, fallback lien manuel mémorisé)
- analyse BG3-pyUpgrade + mod armes existants
