# BG3Tools — Todo List

## P0 — Critique / Fondation

- ~~**BUG** : clic sur "Extraire vers Mods/" (et la plupart des boutons "Tâches" déjà dans le top 3 d'usage) faisait planter tout le TUI sans message d'erreur lisible~~ — fait : cause racine identifiée dans `ActionsScreen._refresh_quick_actions` — `Widget.remove()` est asynchrone chez Textual, donc le remontage d'un bouton "quick action" avec le même id pouvait arriver avant que l'ancien soit réellement retiré du DOM, levant `DuplicateIds` (touchait quasi tous les boutons déjà présents dans le top 3 d'usage, pas seulement "Extraire"). Corrigé (`await bar.query(Button).remove()` avant remontage) et durci en profondeur pour éviter toute récidive silencieuse : les ~20 workers `@work` de l'écran sont passés en `exit_on_error=False`, `on_worker_state_changed` capte désormais toute erreur de worker restante (affichée dans la console de la tâche concernée au lieu de planter tout le TUI), et un nouveau module `bg3_mod_tui/crash_log.py` trace chaque erreur/plantage avec un timestamp dans `crash.log` à la racine du projet
  - (au passage, corrigé aussi : `linking.py._replace_with_hardlink` ne savait pas remplacer un `modsettings.lsx` déjà symlinké par le repli inter-filesystem du commit précédent — `EEXIST` systématique)

### 1. Lecteur natif `.pak` (remplacer Divine.exe)

- ~~**1a-1e.**~~ — fait : `bg3_mod_tui/pak_reader.py` (mmap, header LSPK v15/16/18, index LZ4), parsing meta.lsx/meta.lsf, intégré dans `pak_metadata.read_pak_identity` (le point d'usage réel de Divine.exe — `inventory._match_pak_to_archive` ne lit aucun .pak, seulement les noms de fichiers), avec repli automatique sur Divine.exe y compris sur exception imprévue (`1e`)
  - ⚠️ **non validé contre un vrai `.pak` BG3** (aucun fichier réel disponible dans l'environnement de dev) — tests construits à la main uniquement ; à vérifier en usage réel avant de faire confiance aveuglément aux résultats natifs. Impact limité en pratique : sert à la détection d'archives orphelines, qui ne fait que produire un rapport, jamais de suppression automatique

### 2. Archives orphelines — écriture incrémentale du rapport

- ~~**2a.** Remplacer l'appel unique `_write_orphans_report` par un flush à chaque étape de vérification~~ — fait : nouvelle méthode `_flush_orphans_progress` réécrivant `archives_orphelines.md` à chaque archive traitée dans la boucle Divine.exe (une interruption en cours de route laisse un rapport partiel exploitable au lieu de rien) ; `_write_orphans_report` reste appelée une dernière fois en fin de boucle pour le regroupement final poli (orphelines/non vérifiables)
- ~~**2b.** Format : un commit/étape = une ligne écrite dans `archives_orphelines.md` (UUID archive, statut, action)~~ — fait : chaque ligne de progression (`_orphan_report_row`) porte le nom d'archive, taille, origine, date, et un statut clair (« orpheline confirmée », « faux positif écarté », « non vérifiable ») — adapté par rapport à l'UUID d'archive mentionné à l'origine (une archive peut contenir plusieurs .pak/UUID, le nom de fichier identifie sans ambiguïté la ligne)

## P1 — Haute priorité

### 4. Priorisation Nexus / Mod.io

- **4a.** Règle : si Mod.io version > Nexus version → privilégier Mod.io — bloqué : aucune correspondance fiable Nexus↔mod.io dans le code (ArchiveEntry ne modélise que Nexus), et aucun endpoint (un)subscribe mod.io vérifié — un mapping par nom serait une heuristique dangereuse pour déclencher une action automatique
- **4b.** (un)subscribe auto sur Mod.io lors du switch de source — bloqué pour la même raison que 4a ; en attendant, un vrai bug latent a été corrigé : `extract_archives_to_mods` plantait toute la boucle si un seul .pak était verrouillé (jeu en cours) — désormais isolé par fichier, loggé, `report["failed"]`, archive retentée au passage suivant
- ~~**4c.** Process de vérification de version entre archives locales et Nexus~~ — fait : bouton "Vérifier les mises à jour Nexus...", rapport `nexus_updates.md` (lecture seule, nécessite NEXUS_API_KEY)

### 5. Téléchargements parallèles

- ~~**5a.** Mod.io : téléchargement parallèle sans restriction (pas de rate-limit)~~ — fait : `ThreadPoolExecutor` (`MODIO_MAX_DOWNLOAD_THREADS=8`, borne raisonnable documentée plutôt qu'une vraie limite API)
- ~~**5b.** Nexus : max ~6 threads de DL concurrents~~ — fait : `_NEXUS_MAX_DOWNLOAD_THREADS=6` ; `select_files` (wizard de sélection de variantes) reste strictement séquentiel (un seul écran modal à la fois)
- ~~**5c.** Console dédiée avec barres de progression par thread, sous la console principale~~ — fait : nouvel onglet "Téléchargements" (`DownloadProgressConsole`), une ligne par thread actif avec barre + taille téléchargée/totale
- ~~**5d.** Préparation des wizards suivants pendant qu'un DL tourne (pipeline)~~ — fait : côté Nexus, chaque job est soumis au pool dès qu'il est prêt (`executor.submit`) au lieu d'attendre la fin de la préparation de tous les mods — la boucle de préparation (info + wizard) avance pendant que des téléchargements tournent déjà

### 6. Utilitaire standalone de validation `.pak`

- ~~**6a-6c.**~~ — fait : `bg3_mod_tui/pak_validator.py`, réutilise `pak_reader.PakArchive` (pas de réimplémentation), échantillonne et décompresse les entrées pour détecter une corruption, rapport `{"valid": [...], "invalid": [...]}` + `pak_validation.md`, aucune génération modsettings.lsx ni lancement du jeu
  - ⚠️ hérite de la même limite que `pak_reader` : jamais validé contre un vrai `.pak` BG3, et **pas de repli Divine.exe** ici (contrairement à `pak_metadata`) — une erreur de lecture native est rapportée telle quelle comme "invalide"

### 7. Vue par onglets (Console principale / Outils / Serveur web)

- **PRIORISÉ par Elwingh** : retour des trois consoles visibles distinctes (principale, outil, serveur web) + ajout d'onglets pour séparer les tâches simultanées sur la console principale et la console Outils (pas la console Web, qui n'a pas besoin d'onglets)
- ~~**7a.** Garder les trois consoles de base~~ — déjà en place (4 onglets statiques dans `compose()` : Tâches, Téléchargements, Outils, Web), vérifié après 7b, rien à changer
- ~~**7b.** Console Tâches : si une tâche tourne déjà et qu'un bouton déclenche une écriture → créer un onglet dédié au lieu d'empiler~~ — fait : `ActionsScreen._start_task`/`_acquire_task_console` (nouvel onglet dynamique via `TabbedContent.add_pane` si une tâche est déjà active, détecté via `self._active_tasks` peuplé/vidé sur le cycle de vie des `Worker` Textual) + `_resource_conflict` (verrouillage par étiquette de ressource — "mods-dir", "archives", "native-mods", "modsettings", "tools-dir"/"game-bin-dir" — pour garder mutuellement exclusives les actions qui écrivent dans les mêmes fichiers, même dans des onglets séparés) ; chaque `@work` a son propre groupe Textual (les ~16 workers "Tâches" partageaient tous le groupe "default" avant ce correctif, donc s'annulaient mutuellement dès qu'une autre action était lancée)
- **7c.** Vérifier que les trois consoles (principale/Tâches, Outils, Web) sont bien toutes visibles/accessibles dans l'UI actuelle — confirmer qu'aucune régression n'a masqué l'une d'elles depuis 7a
- **7d.** Étendre le mécanisme d'onglet dynamique par tâche simultanée (`_acquire_task_console` / `_resource_conflict`, actuellement limité à la console Tâches via 7b) à la console Outils uniquement — la console Web n'a pas besoin d'onglets

### 15. Bug UI : clic sur un bouton sélectionne le texte

- **15a.** Les clics sur les boutons sélectionnent le texte du bouton (comportement navigateur/texte par défaut, gênant) — à corriger

## P2 — Moyen terme

### 8. Profils + quick actions

- ~~**8a.** Compteur d'utilisation par bouton/outil/profil (persistant)~~ — fait : `bg3_mod_tui/usage_stats.py` (même pattern que `profiles.py`, JSON par profil), hook générique `ActionsScreen.on_button_pressed` incrémentant chaque bouton `action-*` (hors "Quitter") sans toucher aux ~30 handlers `@on` existants
- ~~**8b.** Affichage des 3 actions les plus utilisées en boutons quick-action en haut d'écran~~ — fait : barre `#quick-actions-bar` (`_refresh_quick_actions`), recalculée en temps réel à chaque clic — un clic quick action rejoue `Button.press()` sur le bouton original, sans dupliquer sa logique

### 9. Fusion bouton "Mise à jour outils" + "Compil Compat Framework" + "ModFixerFork"

- ~~**9a.** Unified button lançant les trois séquences dans l'ordre avec barre de progression globale~~ — fait : bouton "Tout mettre à jour (outils + Compat Framework + Mod Fixer)" (`ActionsScreen.run_update_all`, mêmes `resource_tags` que les 3 actions individuelles qu'il enchaîne — conservées telles quelles, pas de suppression) ; corps de chaque étape factorisé en méthode `_*_task(log) -> bool` (même principe que `_restore_profile_task`) réutilisée à la fois par son bouton dédié et par la séquence unifiée ; enchaînement/progression "[i/3]"/arrêt-au-premier-échec extrait en fonction pure `_run_task_sequence` (testée dans `tests/test_actions_task_tabs.py`, même esprit que `_resource_conflict`) — arrêt choisi plutôt que "continuer coûte que coûte" car Compat Framework et Mod Fixer dépendent explicitement de Divine.exe téléchargé par la 1ère étape
- **9b.** Retirer les 3 boutons d'action individuels ("MAJ des outils", "Compiler Compat. Framework", "Forker Mod Fixer") de l'écran principal — confirmé par Elwingh : le bouton unifié "Tout mettre à jour" couvre déjà les 3, plus besoin de les garder visibles séparément. Ne retirer que les entrées `compose()` + handlers `@on(Button.Pressed, "#action-...")` dédiés ; garder les méthodes `_*_task` (toujours utilisées par `run_update_all`) et les workers `run_build_compat_framework`/`run_build_mod_fixer_fork`/`run_download_tools` si un usage isolé reste utile ailleurs, sinon les retirer aussi

### 16. `data-extractor` : extraction JSON classes/sous-classes/dons/objets depuis les mods

- **16a.** Parcourir la doc des mods (première étape, sans lecture .pak) pour lister classes/sous-classes/dons/objets
- **16b.** Étendre au contenu réel des .pak (réutiliser `pak_reader.py`) une fois 16a en place
- **16c.** Sortie dans des structures JSON adaptées (une structure par type d'entité)

## P3 — Annexe (avant V2/V3/V4)

### 10. Build de classes (page web autonome)

- ~~**10a-10d.**~~ — fait : `bg3_mod_tui/class_builder.py` + `class_data.py`, génère un `.html` autonome (CSS/JS inline, logique de sélection côté client), règle "continuation illimitée d'une classe déjà prise, mais un seul nouveau choix par classe" en Python (testée) et miroir JS
  - ~~pas encore câblé dans l'UI Textual~~ — fait : bouton "Build de classes..." dans `ActionsScreen` (génère la page dans `BG3_Managed/` et l'ouvre dans le navigateur par défaut)
  - ~~**10c.** Graph Mermaid via CDN~~ — remplacé par un graphe natif (chaîne verticale de nœuds confirmés + rangée de choix cliquables en dessous, sur demande explicite d'Elwingh avec croquis à l'appui) : plus aucune dépendance externe, page 100% hors-ligne. Chaque clic sur un choix (continuer la classe active, choisir une sous-classe disponible, ou multiclasser vers une classe encore libre) ajoute un nœud ; les options proposées sont toujours calculées pour rester dans les règles de progression, donc aucun état invalide n'est atteignable via l'UI
  - ~~**données approximatives niveaux 13-20 extrapolés**~~ — retiré sur demande explicite d'Elwingh (« on extrapole rien ») : `class_data.py` est désormais strictement vanilla BG3 (niveau 1→12, plus aucune donnée au-delà), et les sous-classes marquées "à vérifier/à confirmer" (Barbare Wrecker, Ensorceleur Storm) ont été retirées plutôt que gardées avec un doute
  - corrigé au passage (bug de fond révélé par le multiclassage) : les gains par niveau (`features_by_level`/`asi_levels`/déblocage de sous-classe) étaient calculés sur le niveau TOTAL du personnage au lieu du niveau DANS la classe concernée (règle 5e standard) — n'affectait pas les builds mono-classe (d'où le bug resté invisible), mais donnait des résultats faux pour tout multiclassage ; corrigé via `class_builder._level_in_class`, testé
  - **10e.** Mods qui étendent le niveau max ou ajoutent des classes/sous-classes : pas pris en compte automatiquement (aucune métadonnée exploitable dans un `.pak` pour le déduire) — à ajouter explicitement dans `class_data.py`, mod par mod, dès qu'Elwingh liste lesquels de ses mods installés (328 dans `mods_inventory.json`, aucun connu à ce jour) étendent effectivement ça

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

- ~~**13a.** Identifier et citer les licences des outils/inspirations utilisés~~ — fait : `THIRD_PARTY_LICENSES.md` (dépendances Python via PyPI, LSLib/BG3SE/BG3 Mod Manager/BG3 Compatibility Framework/Native Mod Loader via l'API GitHub, licences vérifiées à la source) + mention dans le README ; deux cas non tranchables documentés tels quels (Para Tool : aucune licence détectée sur le dépôt ; Mod Fixer et MoreReactiveCompanions : pages Nexus Mods non accessibles en automatisé — HTTP 403 — usage sous conditions Nexus par défaut)

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
- fork local de Mod Fixer avec meta.lsx propre (remplace ModFixer.pak, backup dans ModFixer.pak.orig, UUID stable entre reconstructions)
