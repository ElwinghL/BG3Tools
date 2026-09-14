# BG3Tools — Todo List

## TODO - Categorie human user

Les points de cette categories sont a trier, reformuler et classer par les agents competents. Cette categorie ne doit pas etre supprimee, elle peut rester vide, accompagne de ce petit texte d'explication.

Rien de non trié à ce jour — les 3 points ajoutés le 2026-09-13 ont été
classés : suppression des boutons superflus déjà faite (voir section 9,
sous-tâche 9b) ; modifications locales BG3SE pour Linux fusionnée avec la
section 11 (11a reformulé, patch fork `ElwinghL/bg3se`) ; détection du
Script Extender par le Mod Manager déplacée en section 24 ci-dessous.

## P0 — Critique / Fondation

- ~~**BUG** : clic sur "Extraire vers Mods/" (et la plupart des boutons "Tâches" déjà dans le top 3 d'usage) faisait planter tout le TUI sans message d'erreur lisible~~ — fait : cause racine identifiée dans `ActionsScreen._refresh_quick_actions` — `Widget.remove()` est asynchrone chez Textual, donc le remontage d'un bouton "quick action" avec le même id pouvait arriver avant que l'ancien soit réellement retiré du DOM, levant `DuplicateIds` (touchait quasi tous les boutons déjà présents dans le top 3 d'usage, pas seulement "Extraire"). Corrigé (`await bar.query(Button).remove()` avant remontage) et durci en profondeur pour éviter toute récidive silencieuse : les ~20 workers `@work` de l'écran sont passés en `exit_on_error=False`, `on_worker_state_changed` capte désormais toute erreur de worker restante (affichée dans la console de la tâche concernée au lieu de planter tout le TUI), et un nouveau module `bg3_mod_tui/crash_log.py` trace chaque erreur/plantage avec un timestamp dans `crash.log` à la racine du projet
  - (au passage, corrigé aussi : `linking.py._replace_with_hardlink` ne savait pas remplacer un `modsettings.lsx` déjà symlinké par le repli inter-filesystem du commit précédent — `EEXIST` systématique)

### 23. Deux bugs trouvés via `crash.log` (session du 2026-09-11, 8 plantages)

`crash_log.py` a fait son travail (aucun des deux ne plante plus tout le TUI),
mais les causes racines ne sont pas corrigées :

- ~~**23a.** `native_mods.py::_hardlink_into` appelait `os.link(source, target)` sans repli~~ — fait : remplacé par `platform_utils.link_or_symlink` (même helper déjà utilisé par `linking.py._replace_with_hardlink` pour ce même bug de fond). Causait **6 des 8 plantages du log** (`OSError: [Errno 18] Invalid cross-device link` en déployant un mod natif — `Native Camera Tweaks`, `Baldur's Priority` — depuis `BG3_Managed/NativeMods/<archive>/` vers `BG3_Managed/Installation BG3/bin/NativeMods/`, deux points de montage différents). Import `os` retiré de `native_mods.py` (devenu inutile)
- ~~**23b.** `AttributeError: 'NoneType' object has no attribute 'render_strips'`~~
  — fait (déjà) : cause racine identifiée rétroactivement — `DownloadProgressConsole`
  (`bg3_mod_tui/widgets/download_console.py`) définissait une méthode `_render()`
  qui écrasait par erreur `Widget._render(self) -> Visual` (méthode interne
  Textual utilisée par le compositeur), retournant `None` au lieu d'un `Visual`.
  Le widget a été introduit le 2026-09-10 (commit `0514688`, sous-tâche 5c) et
  corrigé le 2026-09-13 (commit `5b86738`, "fix/DownloadsTabClickBug",
  renommage en `_refresh_content` + `tests/test_download_console.py`) — la
  session de crash.log qui a produit ces 2 occurrences date du 2026-09-11,
  pile dans cette fenêtre : même bug, déjà résolu avant que cette investigation
  ne démarre. Vérifié en balayant TOUT le projet (`tests/test_no_private_textual_api_shadowing.py`,
  garde-fou générique qui découvre dynamiquement toutes les classes
  Widget/Screen custom de `bg3_mod_tui` et échoue si l'une d'elles redéfinit
  une méthode privée déjà utilisée en interne par Textual) : aucune autre
  collision de ce type n'existe ailleurs dans le code à ce jour

### 1. Lecteur natif `.pak` (remplacer Divine.exe)

- ~~**1a-1e.**~~ — fait : `bg3_mod_tui/pak_reader.py` (mmap, header LSPK v15/16/18, index LZ4), parsing meta.lsx/meta.lsf, intégré dans `pak_metadata.read_pak_identity` (le point d'usage réel de Divine.exe — `inventory._match_pak_to_archive` ne lit aucun .pak, seulement les noms de fichiers), avec repli automatique sur Divine.exe y compris sur exception imprévue (`1e`)
  - ⚠️ **validé depuis contre de vrais `.pak` BG3** via `scripts/compare_pak_reader.py` (croisement Python/Rust/Divine.exe) : identité, table de fichiers et hash de contenu décompressé corrects, MAIS un vrai bug détecté — certaines entrées rapportent une taille de **0** au lieu de la vraie valeur (confirmée par Rust et Divine.exe), cause non encore identifiée — voir `Tools/bg3pythonpaklib/README.md#comparisons`. Impact limité en pratique : sert à la détection d'archives orphelines, qui ne fait que produire un rapport, jamais de suppression automatique — mais le bug de taille reste à corriger avant d'étendre l'usage de ce lecteur (ex: 16b)

### 2. Archives orphelines — écriture incrémentale du rapport

- ~~**2a.** Remplacer l'appel unique `_write_orphans_report` par un flush à chaque étape de vérification~~ — fait : nouvelle méthode `_flush_orphans_progress` réécrivant `archives_orphelines.md` à chaque archive traitée dans la boucle Divine.exe (une interruption en cours de route laisse un rapport partiel exploitable au lieu de rien) ; `_write_orphans_report` reste appelée une dernière fois en fin de boucle pour le regroupement final poli (orphelines/non vérifiables)
- ~~**2b.** Format : un commit/étape = une ligne écrite dans `archives_orphelines.md` (UUID archive, statut, action)~~ — fait : chaque ligne de progression (`_orphan_report_row`) porte le nom d'archive, taille, origine, date, et un statut clair (« orpheline confirmée », « faux positif écarté », « non vérifiable ») — adapté par rapport à l'UUID d'archive mentionné à l'origine (une archive peut contenir plusieurs .pak/UUID, le nom de fichier identifie sans ambiguïté la ligne)

### 24. Détection du Script Extender par le BG3 Mod Manager (hardlink)

- ~~Regarder comment BG3 Mod Manager vérifie la présence du Script Extender pour proposer une correction plus précise qui prenne en compte notre déploiement par hardlink (voir `bg3_mod_tui/game_deploy.py`) plutôt qu'une simple vérification de fichier qui pourrait ignorer/mal interpréter un hardlink~~ — investigué, **pas de bug réel confirmé**, aucun correctif nécessaire :
  - Notre déploiement (`game_deploy.py::deploy_script_extender` → `_hardlink_replace`) fait de `bin/DWrite.dll` un hardlink POSIX (`os.link`, repli symlink en cas d'`EXDEV` via `platform_utils.link_or_symlink`) vers notre copie gérée dans `Tools/BG3 Script Extender/`. Un hardlink partage le même inode : contenu, taille et métadonnées identiques à un fichier copié normalement — indiscernable au niveau du système de fichiers.
  - Code source de BG3 Mod Manager (LaughingLeader/BG3ModManager, `src/GUI/ViewModels/MainWindowViewModel.cs::CheckExtenderUpdaterVersion`, `EXTENDER_UPDATER_FILE = "DWrite.dll"`) : la détection fait `File.Exists(bin/DWrite.dll)` puis lit les métadonnées **embarquées dans le contenu du fichier** via `FileVersionInfo.GetVersionInfo(...)` (ressource `VERSIONINFO` du PE, vérifie que `ProductName` contient "Script Extender"). Ce sont deux vérifications purement basées sur le contenu/octets du fichier ouvert via le chemin — aucune comparaison de chemin canonique, aucun `realpath`, aucun rejet explicite des hardlinks/reparse points. `File.Exists`/`FileVersionInfo` suivent le chemin jusqu'à l'inode comme n'importe quel autre outil, donc un hardlink POSIX (même inode que l'original) y est totalement transparent.
  - Recherche des rapports de bugs communautaires (issues #204, #292, #366, #412, #419, discussion #248) : les cas réels de "Script Extender non détecté malgré sa présence" proviennent du runtime .NET manquant sous Wine/Proton/Lutris (confirmé par les commentaires de l'issue #204 : le problème disparaît après installation du runtime .NET requis) ou de conflits d'ordre de chargement avec Native Mod Loader — aucun signalement lié à un hardlink ou à une méthode de déploiement par lien.
  - Conclusion : le risque décrit dans l'item d'origine (outil externe qui refuserait/mal interpréterait un hardlink) ne se matérialise pas avec BG3 Mod Manager tel qu'il existe aujourd'hui. Aucune modification de `bg3_mod_tui/game_deploy.py` ou `bg3_mod_tui/platform_utils.py` n'est nécessaire.
  - _Rationale_ : ajouté par Elwingh le 2026-09-13, investigué le 2026-09-13 — conclusion "pas de bug réel", conservé ici pour traçabilité au cas où une future version de BG3 Mod Manager changerait sa méthode de détection.

### 25. Bug UI sur l'onglet Téléchargements, à investiguer

- ~~Investiguer un bug latent éventuel sur l'onglet "Téléchargements" (`DownloadProgressConsole`)~~
  — investigué le 2026-09-13, **aucun bug reproductible identifié à ce jour**. Aucune
  observation précise n'a été fournie (pas de repro connue, pas d'entrée `crash.log`) : audit
  de lecture critique de `bg3_mod_tui/widgets/download_console.py` en entier, de son unique
  utilisation dans `bg3_mod_tui/screens/actions.py` (`_on_download_progress`,
  `run_download_mods`), et des deux producteurs de progression dans `mod_pipeline.py`
  (`download_nexus_mods_by_id`/`_download_job`, `download_subscribed_modio_mods`/
  `_download_one`) :
  - `tests/test_no_private_textual_api_shadowing.py` (garde-fou générique introduit pour 23b)
    tourne toujours au vert et couvre bien ce fichier — pas de nouvelle collision d'API privée
    Textual du même genre
  - mutations du widget (`update_progress`/`clear`) toujours faites via `App.call_from_thread`
    depuis les threads du pool de téléchargement (jusqu'à 8 mod.io / 6 Nexus en parallèle),
    donc sérialisées sur le thread UI — pas de race sur `self._slots`
  - génération des `slot_id` vérifiée sans collision possible : `f"nexus-{mod_id}-{file_id}"`
    (un par fichier retenu) et `f"modio-{mod_id}"` (un fichier par mod côté mod.io) ; les deux
    lots (Nexus puis mod.io) s'exécutent en séquence dans `run_download_mods`, jamais en
    parallèle l'un de l'autre, donc pas de collision inter-source non plus
  - nettoyage des lignes de progression vérifié systématique : les deux producteurs appellent
    `on_download_progress(slot_id, label, None, None)` dans un bloc `finally` (succès, échec
    API ou exception inattendue), donc pas de barre qui reste affichée indéfiniment après la
    fin réelle d'un téléchargement
  - suite de tests complète (203 tests) verte, aucune régression
  - **une piste de vigilance non confirmée** (pas un bug prouvé, donc pas corrigée
    spéculativement — préférence du projet) : `_on_download_progress` et `run_download_mods`
    appellent `self.query_one("#downloads-progress", DownloadProgressConsole)` directement
    sur le thread de téléchargement appelant (avant de passer la méthode elle-même à
    `call_from_thread`) — une traversée du DOM Textual hors du thread UI, techniquement en
    dehors du contrat "tout accès aux widgets depuis le thread principal". Aujourd'hui sans
    conséquence connue : `#downloads-progress` vit dans `ActionsScreen`, l'écran racine unique
    et durable de l'appli, jamais démonté/remonté pendant qu'un téléchargement tourne — rien
    à raciner contre. À surveiller si l'architecture change un jour (onglet démonté/reconstruit
    dynamiquement pendant un téléchargement en cours), auquel cas `query_one` pourrait lever
    `NoMatches` sur le thread de téléchargement et faire échouer à tort un mod en cours

## P1 — Haute priorité

### 4. Priorisation Nexus / Mod.io

- **4a.** Règle : si Mod.io version > Nexus version → privilégier Mod.io — bloqué : aucune correspondance fiable Nexus↔mod.io dans le code (ArchiveEntry ne modélise que Nexus), et aucun endpoint (un)subscribe mod.io vérifié — un mapping par nom serait une heuristique dangereuse pour déclencher une action automatique
- **4b.** (un)subscribe auto sur Mod.io lors du switch de source — bloqué pour la même raison que 4a ; en attendant, un vrai bug latent a été corrigé : `extract_archives_to_mods` plantait toute la boucle si un seul .pak était verrouillé (jeu en cours) — désormais isolé par fichier, loggé, `report["failed"]`, archive retentée au passage suivant
- ~~**4c.** Process de vérification de version entre archives locales et Nexus~~ — fait : bouton "Vérifier les mises à jour Nexus...", rapport `nexus_updates.md` (lecture seule, nécessite NEXUS_API_KEY)
- ~~**4d.** Le téléchargement de mods ignore `nexus_updates.md` : rien ne relit `report["outdated"]` pour proposer/prioriser la mise à jour des mods obsolètes~~ — fait : nouvel écran modal `NexusOutdatedModsScreen` (calqué sur `NexusBlacklistScreen`), s'ouvre automatiquement après "Vérifier les mises à jour Nexus..." si `outdated` n'est pas vide ; `download_mods_from_links_file` factorisé en `download_nexus_mods_by_id` (réutilisable), et `redownload_nexus_mod` contourne le filtre "mod déjà présent localement" qui bloquait sinon tout re-téléchargement ciblé

### 5. Téléchargements parallèles

- ~~**5a.** Mod.io : téléchargement parallèle sans restriction (pas de rate-limit)~~ — fait : `ThreadPoolExecutor` (`MODIO_MAX_DOWNLOAD_THREADS=8`, borne raisonnable documentée plutôt qu'une vraie limite API)
- ~~**5b.** Nexus : max ~6 threads de DL concurrents~~ — fait : `_NEXUS_MAX_DOWNLOAD_THREADS=6` ; `select_files` (wizard de sélection de variantes) reste strictement séquentiel (un seul écran modal à la fois)
- ~~**5c.** Console dédiée avec barres de progression par thread, sous la console principale~~ — fait : nouvel onglet "Téléchargements" (`DownloadProgressConsole`), une ligne par thread actif avec barre + taille téléchargée/totale
- ~~**5d.** Préparation des wizards suivants pendant qu'un DL tourne (pipeline)~~ — fait : côté Nexus, chaque job est soumis au pool dès qu'il est prêt (`executor.submit`) au lieu d'attendre la fin de la préparation de tous les mods — la boucle de préparation (info + wizard) avance pendant que des téléchargements tournent déjà

### 6. Utilitaire standalone de validation `.pak`

- ~~**6a-6c.**~~ — fait : `bg3_mod_tui/pak_validator.py`, réutilise `pak_reader.PakArchive` (pas de réimplémentation), échantillonne et décompresse les entrées pour détecter une corruption, rapport `{"valid": [...], "invalid": [...]}` + `pak_validation.md`, aucune génération modsettings.lsx ni lancement du jeu
  - ⚠️ hérite du bug de taille désormais connu sur `pak_reader` (voir section 1 ci-dessus), et **pas de repli Divine.exe** ici (contrairement à `pak_metadata`) — une erreur de lecture native est rapportée telle quelle comme "invalide"

### 7. Vue par onglets (Console principale / Outils / Serveur web)

- **PRIORISÉ par Elwingh** : retour des trois consoles visibles distinctes (principale, outil, serveur web) + ajout d'onglets pour séparer les tâches simultanées sur la console principale et la console Outils (pas la console Web, qui n'a pas besoin d'onglets)
- ~~**7a.** Garder les trois consoles de base~~ — ⚠️ le premier passage (7a/7c initiaux) avait laissé les 4 consoles dans un SEUL `TabbedContent` ("Tâches", "Téléchargements", "Outils", "Web") : une seule visible à la fois, contrairement à la demande "trois consoles VISIBLES DISTINCTES" ci-dessus — repéré par Elwingh en testant l'UI ("je n'ai pas le retour de ma console principale, de la console outil en dessous et de la console web à droite"). Corrigé : `compose()` sépare maintenant réellement les trois zones dans `#logs-column` — `#tasks-tabs` (Tâches + Téléchargements + onglets dynamiques) en haut à gauche, `#web-console-log` (pas d'onglets) en haut à droite, `#tools-tabs` (Outils + onglets dynamiques) sur toute la largeur en bas — les trois toujours visibles simultanément, plus besoin de cliquer pour changer. Bordures rouge/vert/bleu utilisées un temps comme repères visuels pour valider le placement, puis retirées à la demande d'Elwingh au profit des couleurs `$panel`/`$accent` d'origine (les couleurs par console n'étaient pas voulues comme identité visuelle permanente)
- ~~**7b.** Console Tâches : si une tâche tourne déjà et qu'un bouton déclenche une écriture → créer un onglet dédié au lieu d'empiler~~ — fait : `ActionsScreen._start_task`/`_acquire_task_console` (nouvel onglet dynamique via `TabbedContent.add_pane` si une tâche est déjà active, détecté via `self._active_tasks` peuplé/vidé sur le cycle de vie des `Worker` Textual) + `_resource_conflict` (verrouillage par étiquette de ressource — "mods-dir", "archives", "native-mods", "modsettings", "tools-dir"/"game-bin-dir" — pour garder mutuellement exclusives les actions qui écrivent dans les mêmes fichiers, même dans des onglets séparés) ; chaque `@work` a son propre groupe Textual (les ~16 workers "Tâches" partageaient tous le groupe "default" avant ce correctif, donc s'annulaient mutuellement dès qu'une autre action était lancée)
- ~~**7c.** Vérifier que les trois consoles (principale/Tâches, Outils, Web) sont bien toutes visibles/accessibles dans l'UI actuelle~~ — voir 7a ci-dessus : PAS le cas au premier passage (4 onglets dans un seul `TabbedContent`), corrigé par la même refonte de layout
- ~~**7d.** Étendre le mécanisme d'onglet dynamique par tâche simultanée (`_acquire_task_console` / `_resource_conflict`, jusque-là limité à la console Tâches via 7b) à la console Outils~~ — fait : `_ActiveTask`/`_acquire_task_console`/`_start_task` généralisés avec un paramètre `pool` ("tasks" -> `#tasks-tabs`, "tools" -> `#tools-tabs`, voir `_main_console_for_pool`/`_tabbed_content_for_tab`) ; le verrouillage par ressource (`_resource_conflict`) reste calculé sur `self._active_tasks` en entier, tous pools confondus (une tâche "Outils" et une tâche "Tâches" qui écrivent toutes deux dans Mods/ restent mutuellement exclusives). Routés vers le pool "tools" : "MAJ des outils", "Compiler Compat. Framework", "Forker Mod Fixer", "Tout mettre à jour" (auparavant loggués à tort dans l'onglet "Tâches" malgré leur thème "Outils"), ainsi que "Lancer un outil...", "Ouvrir protontricks" et "Optimiser le préfixe" (auparavant hors mécanisme : plusieurs lancements simultanés entrelaçaient leurs logs dans `#tools-log` sans séparation). Effet de bord corrigé au passage : `run_optimize_prefix` n'avait pas de `group=` explicite sur son `@work`, partageant le groupe "default" avec `run_validate_paks` (même bug de fond que 7b, un lancement pouvait annuler l'autre)

### 15. Bug UI : clic sur un bouton sélectionne le texte

- ~~**15a.** Les clics sur les boutons sélectionnent le texte du bouton (comportement navigateur/texte par défaut, gênant)~~ — fait : cause racine bug amont Textual (`Button.ALLOW_SELECT = False` non respecté au clic entre Textual 2.0.0 et 3.0.0, corrigé en amont par Textualize/textual#5627) ; plancher relevé à `textual>=3.0` dans `pyproject.toml`

## P2 — Moyen terme

### 8. Profils + quick actions

- ~~**8a.** Compteur d'utilisation par bouton/outil/profil (persistant)~~ — fait : `bg3_mod_tui/usage_stats.py` (même pattern que `profiles.py`, JSON par profil), hook générique `ActionsScreen.on_button_pressed` incrémentant chaque bouton `action-*` (hors "Quitter") sans toucher aux ~30 handlers `@on` existants
- ~~**8b.** Affichage des 3 actions les plus utilisées en boutons quick-action en haut d'écran~~ — fait : barre `#quick-actions-bar` (`_refresh_quick_actions`), recalculée en temps réel à chaque clic — un clic quick action rejoue `Button.press()` sur le bouton original, sans dupliquer sa logique

### 9. Fusion bouton "Mise à jour outils" + "Compil Compat Framework" + "ModFixerFork"

- ~~**9a.** Unified button lançant les trois séquences dans l'ordre avec barre de progression globale~~ — fait : bouton "Tout mettre à jour (outils + Compat Framework + Mod Fixer)" (`ActionsScreen.run_update_all`, mêmes `resource_tags` que les 3 actions individuelles qu'il enchaîne — conservées telles quelles, pas de suppression) ; corps de chaque étape factorisé en méthode `_*_task(log) -> bool` (même principe que `_restore_profile_task`) réutilisée à la fois par son bouton dédié et par la séquence unifiée ; enchaînement/progression "[i/3]"/arrêt-au-premier-échec extrait en fonction pure `_run_task_sequence` (testée dans `tests/test_actions_task_tabs.py`, même esprit que `_resource_conflict`) — arrêt choisi plutôt que "continuer coûte que coûte" car Compat Framework et Mod Fixer dépendent explicitement de Divine.exe téléchargé par la 1ère étape
- ~~**9b.** Retirer les 3 boutons d'action individuels ("MAJ des outils", "Compiler Compat. Framework", "Forker Mod Fixer") de l'écran principal~~ — fait : entrées `compose()` (`#action-tools`/`#action-compat-framework`/`#action-mod-fixer-fork`) et handlers `@on(Button.Pressed, "#action-...")` dédiés (`handle_tools`/`handle_compat_framework`/`handle_mod_fixer_fork`) retirés, ainsi que les workers `run_download_tools`/`run_build_compat_framework`/`run_build_mod_fixer_fork` (grep confirmant qu'ils n'étaient plus référencés que par ces handlers). Les méthodes `_*_task` sont conservées telles quelles, toujours utilisées par `run_update_all`. `_action_button_lookup`/`_refresh_quick_actions` (8b) filtrent déjà sur les boutons réellement montés (`#menu-buttons Button`), donc les quick actions basées sur d'anciens usages de ces 3 boutons disparaissent automatiquement sans code de filtrage supplémentaire

### 16. `data-extractor` : extraction JSON classes/sous-classes/dons/objets depuis les mods

- ~~**16a.** Parcourir la doc des mods (première étape, sans lecture .pak) pour lister classes/sous-classes/dons/objets~~ — fait : `bg3_mod_tui/data_extractor.py` (`build_documentation_index`), construit la documentation best-effort de chaque .pak installé à partir de `mods_inventory.json` (`inventory.build_inventory`, pas de lecture .pak) + résumé Nexus optionnel (`providers.nexus.NexusClient.mod_info`, best-effort) scanné pour des mentions de classes/sous-classes/dons/objets (`scan_entity_mentions`, expressions multi-mots volontairement conservatrices — "don"/"objet"/"classe" seuls sont trop ambigus en français courant, testé). Un échec Nexus sur un mod (clé absente, 404, réseau) est journalisé et ignoré, pas d'échec global (même tolérance que `pak_metadata.build_deployed_uuid_index`). Testé (`tests/test_data_extractor.py`, 16 tests)
- ~~**16b.** Étendre au contenu réel des .pak (réutiliser `pak_reader.py`) une fois 16a en place~~ — **fait partiellement** (périmètre réduit mais fiable, assumé) : `data_extractor.extract_pak_entities` + `parse_stats_entries` extraient réellement les dons/objets déclarés dans `Stats/Generated/Data/{Feat,Weapon,Armor,Object}.txt` (format "stats" texte de Larian — `new entry "Nom"` / `type "..."` / `data "Clé" "Valeur"`, documenté par la communauté de modding DOS2/BG3), via `PakArchive.find_suffix` (`bg3_mod_tui/data_extractor.py`, nouvelle dataclass `PakEntity`). Testé sur des `.pak` **SYNTHÉTIQUES** construits à la main (`tests/test_data_extractor.py`, réutilise `_build_v18_pak_multi` de `tests/test_pak_reader.py`) — **NON vérifié contre un vrai `.pak` BG3**, aucun disponible dans cet environnement de dev (même réserve que `pak_reader`/`pak_metadata`). Volontairement NON couvert (documenté en commentaire plutôt que deviné) : classes/sous-classes via `Progression.lsx`/`ClassDescriptions.lsx` (schéma de nœuds LSX non confirmé contre un vrai fichier) et objets via `RootTemplates/*.lsf` (associer un GUID de gabarit à un nom exploitable nécessiterait un vrai parseur de chunks LSF, pas juste une regex d'UUID comme pour `meta.lsf`)
- **16c.** Sortie dans des structures JSON adaptées (une structure par type d'entité) — squelette posé : `data_extractor.documentation_index_to_json`/`save_documentation_index` produisent déjà le format visé (`classes`/`sous_classes`/`dons`/`objets`, une liste par type) pour les MENTIONS (16a) ; `PakEntity` (16b) reste séparé pour l'instant (pas encore fusionné dans ce JSON) — à faire une fois 16b validé contre de vrais .pak, et une fois les classes/sous-classes couvertes

### 18. Audit de compatibilité et de syntaxe des mods (BG3 Compatibility Framework)

- Objectif : outil parcourant nos mods pour vérifier que chaque mod enregistre correctement ses classes/sous-classes/sorts/passifs pour l'injection dynamique par le Compatibility Framework — à faire marcher avec `data-extractor` (section 16, notamment 16a qui parcourt déjà la doc des mods)
- ~~**18a.** Fichiers de config et dépendances : dépendance au Script Extender et/ou au Compatibility Framework déclarée (`meta.lsx` ou config JSON) ; présence de `CompatibilityFrameworkConfig.json` (ou appel API Lua dans `ScriptExtender/Lua/BootstrapServer.lua`) ; JSON valide (linter/validateur)~~ — fait : `bg3_mod_tui/compat_audit.py` (`audit_mod`/`audit_installed_mods`), câblé côté UI (`ActionsScreen.run_compat_audit`, rapport `compat_framework_audit.md`). Lecture native des .pak déployés (`pak_reader.PakArchive`, sans repli Divine.exe — limite documentée). Un mod sans `CompatibilityFrameworkConfig.*` ni appel API Lua est `applicable=False` (hors scope, pas une erreur).
- ~~**18b.** Syntaxe des GUIDs : tous les identifiants (`ClassGuid`, `SubClassGuid`, `SpellListGuid`, `PassiveGuid`, etc.) au format UUID v4 valide ; pas de GUID factice/exemple (`00000000-0000-0000-0000-000000000000`) ; pour les sous-classes, `ParentGuid` correspond bien au `ClassGuid` de la classe parente (vanilla ou custom)~~ — fait : `_classify_guid`/`_collect_guids` (format v4 strict avec repli "générique mais pas v4"/"invalide", détection du GUID factice). Pas de référentiel des GUIDs vanilla dans ce dépôt (cherché, absent) → cohérence `ParentGuid`/`ClassGuid` limitée à la cohérence INTERNE entre mods installés scannés (`_check_subclass_parent_consistency`, via `ClassDescriptions[].UUID` uniquement — pas `Progressions[].UUID`, qui peut être une simple Progression vanilla patchée), comme prévu par ce TODO en absence de référentiel.
- ~~**18c.** Déclarations d'injection : nommage exact des mots-clés d'action (`AddSubclass`, `InsertSpell`, `InsertPassive`, `AddSelector`, etc.) ; `Target` pointe vers la bonne table/liste de sorts existante (vanilla ou lib communautaire) ; cas particuliers — `Level` renseigné quand nécessaire pour sorts/passifs, `Remove`/action dédiée correcte pour suppressions/remplacements~~ — fait, avec un écart constaté à la lecture du code source du submodule `Tools/BG3-Compatibility-Framework` (épinglé) : les noms d'exemple du TODO (`AddSubclass`, `InsertSpell`, `AddSelector`) ne sont PAS les vrais noms de l'API (`Api.InsertSubClasses`, `Api.InsertSpellStrings`, `Api.InsertSelectors`...) — `KNOWN_LUA_API_FUNCTIONS`/`KNOWN_JSON_ACTIONS` dans `compat_audit.py` utilisent le vrai vocabulaire extrait du code, donc détectent justement ce genre de faute de frappe. `Target`/`Type` validé structurellement pour `Progressions`/`Lists`/`ClassDescriptions` (sections dont la forme exacte est connue) ; les autres sections n'ont que la vérification générique (mot-clé `Action`) — valider `Type`/`Target` contre les vraies Stats du jeu demanderait un référentiel vanilla (16b/16c, `data-extractor`, hors scope statique). Cas particulier notable détecté : `Action: Insert` sur une entrée `Progressions[].Subclasses[]` JSON n'est JAMAIS appliqué par cette version du Framework (voir `ProgressionHandler.lua`) — signalé en avertissement dédié. `Level` : aucun champ `Level` dans le schéma JSON réel de cette version (le niveau est porté par la Progression elle-même, pas par une clé séparée) — pas de check dédié, documenté comme limite dans `compat_audit.py`.
- **18d.** Test et validation en jeu : logs Script Extender sans erreur/avertissement du Compatibility Framework au chargement (ex. `[CF] Error: Invalid UUID`, `[CF] Failed to insert...`) ; validation visuelle en jeu (création de perso / montée de niveau) que l'élément apparaît sans écraser les autres mods actifs — ce point reste manuel (nécessite le jeu lancé), 18a-18c peuvent être automatisés statiquement

### 17. Optimisation du build Rust (`rust/pak_reader_rs`) — profil release

- ~~**17a.** Auditer un profil `[profile.release]` optimisé pour `rust/pak_reader_rs` et comparer les performances AVANT/APRÈS sur `scripts/compare_pak_reader.py`~~ — fait : `[profile.release]` ajouté (`opt-level = 3`, `lto = "fat"`, `codegen-units = 1`), **sans** `panic = "abort"` (incompatible avec un binding PyO3 — `catch_unwind` a besoin du unwinding pour convertir un panic Rust en exception Python à la frontière FFI ; `abort` tuerait le process Python hôte entier). Gain mesuré sur 47 `.pak` réels/1018 entrées hashées : indexing 0.06s→0.01s, extraction/décompression 10.48s→0.78s (~13x), correctness inchangée. Documenté dans `Tools/bg3rustpaklib/README.md#comparisons`

### 19. Build complet du fork LSLib (`Tools/ExportTools`, remote ElwinghL/lslib)

Objectif du fork : lire/écrire/éditer des `.pak` — rien d'autre en priorité. Si le
reste de LSLib (Story/Osiris, GR2/Granny, VirtualTextures, savegames) doit être
sacrifié pour y arriver, tant pis.

- ~~**19a.** Corriger le crash de `extract-packages` (mode batch, action native LSLib
  pour extraire tous les .pak d'un dossier en un seul lancement de process — voir
  `scripts/compare_pak_reader.py --divine-mode batch`)~~ — fait : `SetUpAndValidate`
  parsait `--input-format` via `GetResourceFormatByString` (LSX/LSB/LSF/LSJ
  seulement, jamais "pak") même pour `extract-packages`, provoquant une
  `ArgumentException` non gérée (crash CLR complet sous Wine) avant même d'atteindre
  `BatchExtract` (qui n'utilise que la chaîne brute). Correctif poussé sur
  `ElwinghL/lslib`, branche `fix/PakBatchExtractSupport` (pas encore mergé sur
  `main` du fork — en attente d'accord explicite, cf. règle CLAUDE.md sur les
  merges).
- ~~**19b.** Build complet du fork non vérifié localement~~ — **fait, en gardant
  uniquement le périmètre .pak** (option "tant pis" assumée pour
  Story/Granny/VirtualTextures/savegames) :
  - Diagnostic confirmé : `LSLibNative` (`.vcxproj` C++, lecteur GR2/Granny)
    nécessite MSVC ; le parser Osiris (Story/Goal) nécessite GPLex 1.2.2 +
    GPPG 1.5.2 (exécutables Windows, absents du dépôt) pour générer
    `Goal.lex.cs`/`Goal.yy.cs`/`StoryHeader.lex.cs`/`StoryHeader.yy.cs` — aucun des
    deux n'a d'équivalent Linux.
  - Correctif préparé sur une branche locale **non poussée** du fork,
    `fix/LinuxBuildPakOnlyScope` (basée sur `main` du fork au commit `551cff1`,
    qui inclut déjà 19a) : retire `LSLibNative` du solution/`.csproj`, exclut
    `Granny/**`, `VirtualTextures/**`, `LS/Story/**`, `LS/Save/**` de la
    compilation de `LSLib.csproj` (`<Compile Remove>`, pas de suppression de
    fichiers sur disque — réversible), retire le `PreBuildEvent` GPLex/GPPG, et
    trimme `LSTools.sln` + les 3 fichiers CLI de Divine (`CommandLineArguments.cs`,
    `CommandLineActions.cs`, `CommandLineDataProcessor.cs`) pour ne garder que les
    actions `create-package;list-package;extract-single-file;extract-package;
    extract-packages;convert-resource;convert-resources;convert-loca` (retrait de
    `convert-model`, `convert-models`, `build-vt`). `CommandLineGR2Processor.cs`
    exclu du build de `Divine.csproj` plutôt que supprimé, pour rester réversible.
  - Une vraie dépendance native est restée dans le périmètre .pak lui-même :
    `PackageReader.cs` appelait `Native.LZ4FrameCompressor.Decompress()`
    (`LSLibNative/lz4wrapper.cpp`) pour décompresser les paquets "solid" (tous les
    fichiers compressés en un seul flux LZ4 frame). Remplacé par le décodeur LZ4
    frame managé déjà référencé ailleurs dans le projet
    (`K4os.Compression.LZ4.Streams`, `LZ4Stream.Decode`), même pattern que
    `Compression.cs`. `ModResources.cs` utilisait aussi l'enum `TargetGame`
    (définie dans `LS/Story/Compiler/CompilationContext.cs`, donc exclue) —
    remplacée par l'enum équivalent déjà présent `LSLib.LS.Enums.Game`.
  - **Build vérifié** : `dotnet build Divine/Divine.csproj -c Release` réussit
    sans erreur (1 seul warning `CS1998` préexistant, sans rapport) sous .NET 8
    dans le conteneur `distrobox bg3tools-dotnet` (Fedora). `dotnet
    Divine/bin/Release/net8.0/Divine.dll` s'exécute et affiche l'usage attendu
    (surface d'actions réduite au pak/resource/loca, confirmant le trim).
    Reproductible via `scripts/lslib_fork_linux_build/build_lslib_fork_linux.sh`
    (clone + applique `scripts/lslib_fork_linux_build/0001-linux-build-pak-only-scope.patch`
    + build ; script testé de bout en bout).
  - **Poussé sur `ElwinghL/lslib`** (2026-09-13, autorisation explicite d'Elwingh) :
    branche `fix/LinuxBuildPakOnlyScope`, 2 commits (le trim de périmètre ci-dessus
    + le fix `TryToValidatePath` du second patch, voir plus bas) — build revérifié
    sur cette branche avant push (`dotnet build` → 0 erreur). PR pas ouverte (pas
    demandé) : https://github.com/ElwinghL/lslib/pull/new/fix/LinuxBuildPakOnlyScope
  - Limitation levée depuis (voir `Tools/nmcm_patches/AbsoluteDefeat/README.md`,
    section 20b) : un vrai test `create-package` de bout en bout (packager un
    mod source réel, relire le `.pak` produit via `list-package` ET
    `pak_reader.py`) a révélé **deux bugs Linux** du fork, corrigés localement
    (non poussés) via un second patch,
    `scripts/lslib_fork_linux_build/0002-fix-linux-path-validation.patch`
    (appliqué automatiquement par `build_lslib_fork_linux.sh`) :
    1. `Divine.CLI.CommandLineActions.TryToValidatePath` plantait
       (`System.InvalidOperationException: This operation is not supported for
       a relative URI`) sur TOUT chemin absolu Unix passé à `-s`/`-d`, y
       compris hors de ce projet — `Uri.TryCreate(...).IsFile` ne reconnaît
       une syntaxe Windows (lettre de lecteur/UNC/`file://`) que sous cette
       forme, un chemin Unix étant parsé comme URI relative. Corrigé en
       remplaçant ce détour par `Path.IsPathRooted(path)` seul.
    2. Packager (`create-package`, testé avec `none` et `zlib`) depuis une
       source vivant sur le point de montage externe `M2`
       (`/run/media/system/M2/BG3Tools/…`, la racine même de ce projet)
       produit un `.pak` illisible par Divine lui-même (`list-package`
       échoue) ET par `pak_reader.py`, sans rapport avec le contenu du mod
       (bisecté fichier par fichier) ni avec un seuil de nombre de fichiers
       (reproduit et non-reproduit sur des arbres synthétiques). Cause racine
       non identifiée (probable particularité mmap/lecture de fichier de ce
       point de montage sous ce build .NET). Contournement appliqué : stager
       une copie de la source ailleurs (`/tmp`) avant `create-package`, ce qui
       produit systématiquement un `.pak` valide — à creuser si ce point de
       montage doit être utilisé plus largement pour du packaging. Ce second
       correctif est INCLUS dans la branche poussée `fix/LinuxBuildPakOnlyScope`
       (2 commits, voir ci-dessus).
- **19c.** Une fois un build fonctionnel obtenu : basculer `Tools/ExportTools`
  (sous-module git, actuellement `Norbyte/lslib`) vers `ElwinghL/lslib`, mettre à
  jour `Tools/TOOLS.md`, re-épingler le commit, et relancer
  `scripts/compare_pak_reader.py --divine-mode batch` sur le profil réel pour
  mesurer l'écart avec le mode per-file (voir `THIRD_PARTY_LICENSES.md` à ajuster
  aussi si la source du binaire change).

## P3 — Annexe (avant V2/V3/V4)

### 10. Build de classes (page web autonome)

- ~~**10a-10d.**~~ — fait : `bg3_mod_tui/class_builder.py` + `class_data.py`, génère un `.html` autonome (CSS/JS inline, logique de sélection côté client), règle "continuation illimitée d'une classe déjà prise, mais un seul nouveau choix par classe" en Python (testée) et miroir JS
  - ~~pas encore câblé dans l'UI Textual~~ — fait : bouton "Build de classes..." dans `ActionsScreen` (génère la page dans `BG3_Managed/` et l'ouvre dans le navigateur par défaut)
  - ~~**10c.** Graph Mermaid via CDN~~ — remplacé par un graphe natif (chaîne verticale de nœuds confirmés + rangée de choix cliquables en dessous, sur demande explicite d'Elwingh avec croquis à l'appui) : plus aucune dépendance externe, page 100% hors-ligne. Chaque clic sur un choix (continuer la classe active, choisir une sous-classe disponible, ou multiclasser vers une classe encore libre) ajoute un nœud ; les options proposées sont toujours calculées pour rester dans les règles de progression, donc aucun état invalide n'est atteignable via l'UI
  - ~~**données approximatives niveaux 13-20 extrapolés**~~ — retiré sur demande explicite d'Elwingh (« on extrapole rien ») : `class_data.py` est désormais strictement vanilla BG3 (niveau 1→12, plus aucune donnée au-delà), et les sous-classes marquées "à vérifier/à confirmer" (Barbare Wrecker, Ensorceleur Storm) ont été retirées plutôt que gardées avec un doute
  - corrigé au passage (bug de fond révélé par le multiclassage) : les gains par niveau (`features_by_level`/`asi_levels`/déblocage de sous-classe) étaient calculés sur le niveau TOTAL du personnage au lieu du niveau DANS la classe concernée (règle 5e standard) — n'affectait pas les builds mono-classe (d'où le bug resté invisible), mais donnait des résultats faux pour tout multiclassage ; corrigé via `class_builder._level_in_class`, testé
  - **10e.** Mods qui étendent le niveau max ou ajoutent des classes/sous-classes : pas pris en compte automatiquement (aucune métadonnée exploitable dans un `.pak` pour le déduire) — à ajouter explicitement dans `class_data.py`, mod par mod, dès qu'Elwingh liste lesquels de ses mods installés (328 dans `mods_inventory.json`, aucun connu à ce jour) étendent effectivement ça

### 11. Console extender intercepter/flux

- **11a.** ~~Outil interceptant la console du script extender (Proton lag) → rapport dans un terminal TUI lisible~~ **reformulé par Elwingh** : le besoin réel n'est PAS de lire les logs (`*.log` sous `LogDirectory`) mais d'intercepter les vrais flux I/O de la console interactive BG3SE (un REPL Lua, `AllocConsole()`/`ReadConsoleW` dans `CoreLib/Console.cpp` et `BG3Extender/Extender/Shared/Console.cpp`, upstream Norbyte/bg3se) pour pouvoir taper des commandes Lua depuis un terminal Linux classique plutôt que la console Win32 native (laggy sous le rendu GUI de Wine/Proton). Première implémentation (tail de logs, lecture seule) reconnue insuffisante et **revert** de `main`.
- **11b/11c.** ~~Transmission bidirectionnelle + auto-complétion~~ — **design + code écrits (branche `feat/BG3SEBidirectionalConsole`), build C++ bloqué** :
  - Piste retenue après lecture de `CoreLib/Console.cpp`/`BG3Extender/Extender/Shared/Console.cpp` : pas de named pipe Windows (resterait interne au wineserver, pas trivialement exposable côté Linux) mais un **socket TCP en boucle locale (127.0.0.1)**, transparent à travers Proton puisque winsock s'appuie directement sur la pile réseau de l'hôte. La codebase avait déjà exactement ce pattern pour le débogueur Osiris/Lua (`SocketInterface`/`DebugInterface.cpp`, framing par longueur) — réutilisé tel quel plutôt que réinventé.
  - Nouvelle classe `RemoteConsole` (`BG3Extender/Extender/Shared/RemoteConsole.{h,cpp}`, sous-classe de `SocketInterface`) : protocole texte à tags (`'L'` ligne de sortie, `'C'` commande, `'T'`/`'R'` requête/réponse de complétion). Démarrée par `DebugConsole::CreateRemoteConsole()`, appelée depuis `dllmain.cpp` **indépendamment** de `CreateConsole`/`AllocConsole` (config `EnableRemoteConsole`/`RemoteConsolePort`, port 9997 par défaut) — fonctionne donc même sans la console Win32 native, ce qui répond directement au problème de lag Wine/Proton. Complétion (11c) : commandes spéciales + énumération des globales Lua `_G` du contexte courant (`lua_next`, même pattern que `ExecLuaCommand` existant) ; complétion multi-niveaux (`Ext.I...`) pas implémentée.
  - **NON buildé/testé côté C++** : aucun toolchain Windows dans cet environnement (`which mingw-w64-g++ x86_64-w64-mingw32-g++ wine` → absents ; seul `clang-cl` présent via linuxbrew, mais sans Windows SDK/`Windows.h`/`WinSock2.h` ni MSBuild pour driver les `.vcxproj`) — même blocage de fond que la section 19 (LSLibNative). Code écrit en miroir aussi fidèle que possible des patterns déjà existants dans cette codebase (`ExecLuaCommand`, `SocketInterface`), committé sur une branche locale **non poussée** du sous-module (`feat/RemoteConsoleSocket`, base `Norbyte/bg3se` — le fork `ElwinghL/bg3se` mentionné comme piste n'existe pas comme remote/sous-module de ce dépôt et n'a pas été créé, pour ne rien pousser sans accord explicite, même politique que `ElwinghL/lslib`). Le pointeur de sous-module du dépôt parent n'a PAS été mis à jour vers ce commit (resterait cassé pour quiconque n'a pas cette branche locale).
  - Côté Python (`bg3_mod_tui/`), en revanche, **testé et fonctionnel** : `bg3se_remote_console.py` (client socket, protocole vérifié par 5 tests contre un faux serveur qui reproduit le protocole C++ à l'identique) + `widgets/bg3se_console.py` (ConsoleLog + Input + Tab-complétion façon shell, préfixe commun le plus long) intégré comme nouvel onglet "Console BG3SE" du `TabbedContent` Outils dans `ActionsScreen` — montage Textual vérifié manuellement (tous les descendants présents, pas d'exception). Prêt à parler à un vrai process de jeu dès que le patch C++ sera buildé (par Elwingh, ou dans un environnement avec toolchain Windows) et le port 9997 atteignable.
  - **Reste ouvert** : build + test en conditions réelles du patch C++ (bloqué faute de toolchain), puis validation bout-en-bout avec le vrai jeu ; complétion multi-niveaux (`Ext.I...`) si le besoin s'en fait sentir.

## P4 — Futur

### 20. NMCM (Native Mod Configuration Menu) et interface MCM

- ~~**20a.** Ajouter NMCM comme dépendance suivie, même logique que les outils suivis dans `Tools/TOOLS.md`~~ — fait : ligne ajoutée dans `Tools/TOOLS.md`, sous-module git `Tools/bg3-nmcm` (pattern identique aux autres outils GitHub suivis, `_add_or_update_git_submodule`), licence MIT documentée dans `THIRD_PARTY_LICENSES.md` (vérifiée via l'API GitHub)
- ~~**20b.** Patch pilote : portage/patch d'un mod déjà compatible MCM pour lui donner une interface NMCM~~ — fait (statiquement) : `Tools/nmcm_patches/AbsoluteDefeat/` — nouveau mini-mod séparé `AbsoluteDefeat_NMCM_Bridge` (UUID `4af12fa8-50e7-4a17-8ddc-8c6ef83df8c7`, slot NMCM 3 — vérifié libre dans `docs/slot-registry.md`) donnant à Absolute Defeat (déjà installé) une page NMCM en plus de sa page MCM existante, sans toucher à `AbsoluteDefeat.pak` : 2 checkbox + 1 stepper (0-2, `debug_level`) + 2 boutons, goal Osiris qui écrit dans `DB_ADNB_*`/stamp les passives ET appelle 3 PROCs custom capturés côté Lua (`Ext.Osiris.RegisterListener` sur `PROC_ADNB_SyncSetting`/`Fire`/`RequestSync`) qui répercutent dans le stockage MCM réel via `Mods.BG3MCM.MCMAPI:SetSettingValue` (lu dans le vrai Lua d'Absolute Defeat, `GetSettingValue` confirmé, `SetSettingValue` extrapolé par symétrie — voir README) ; les 2 boutons (Surrender/Emergency Stop) relayés côté client (`Ext.Net.PostMessageToServer` vers les canaux exacts d'Absolute Defeat, `AD_Surrender`/`AD_AttemptSoftlockFix`, confirmés dans son Lua) car un `RegisterNetListener` serveur ne répond qu'à un message venant réellement d'un client. `.pak` buildé et relu (Divine `list-package` + `pak_reader.py`, 10 fichiers, identité correcte) via le fork LSLib Linux (section 19) — **2 bugs Linux du fork découverts et patchés localement au passage** (non poussés sur le remote) : `TryToValidatePath` plantait sur TOUT chemin absolu Unix (`Uri.IsFile` suppose une syntaxe Windows — patch `0002-fix-linux-path-validation.patch`), et packager depuis une source vivant sur le point de montage `M2` produit un `.pak` illisible quelle que soit la méthode de compression (contournement : stager la source ailleurs avant `create-package`, cause racine non identifiée). Non testable en jeu ici (pas de jeu lancé) — checklist de validation manuelle dans le README du patch.
- ~~**20c.** 2e patch pilote, sur `feat/NMCM-VisibleShields-Patch` : 2e candidat 100% portable identifié en 20b~~ — fait (statiquement) : `Tools/nmcm_patches/VisibleShields/` — même pattern, nouveau mini-mod séparé `VisibleShields_NMCM_Bridge` (UUID `d9f90e77-b06b-4f62-b777-7f31718e42e0`, slot NMCM 4 — slot 3 déjà pris par le patch 20b, vérifié libre pour le 4 dans `docs/slot-registry.md`) donnant à Visible Shields - Universal (déjà installé) une page NMCM, sans toucher à `VisibleShieldsU.pak` : 1 dropdown de 3 valeurs (`share_mode`, `enum`) + 1 stepper (0-2, `debug_level`). **Premier patch du projet à ponter un setting `enum`** : contrôle natif NMCM dropdown-de-N-valeurs (`examples/controls/list`, une passive marqueur par valeur) plutôt qu'un mécanisme radio multi-checkbox improvisé. Point notable confirmé (pas deviné) en lisant le vrai `BootstrapClient.lua` de Visible Shields Universal : MCM stocke un `enum` sous la forme de la chaîne de choix brute, pas un index — l'index Osiris (0/1/2) n'est converti en la chaîne exacte du blueprint que côté Lua (`BootstrapServer.lua`). `.pak` buildé et relu (Divine `list-package` + `pak_reader.py`, 9 fichiers, identité correcte) via le fork LSLib Linux, script de build désormais sans étape manuelle pour le patch `0002` (appliqué automatiquement). Non testable en jeu ici — checklist de validation manuelle dans le README du patch.

### 21. Isoler le temps de lecture Rust pur (sans PyO3/Python) dans le comparatif

- ~~**21a.** Ajouter un chemin de mesure isolé (binaire/exemple Rust autonome, pas de Python dans la boucle) pour départager le coût réel de lecture `.pak` du coût du binding PyO3~~ — fait : nouvel exemple `native_timing.rs` dans `Tools/bg3rustpaklib`, nouveau chemin `--tool rust-native` dans `scripts/compare_pak_reader.py` (parse son JSON, affiche l'overhead FFI/binding par fichier et au total quand les rapports `rust`/`rust-native` sont présents). Aucun chiffre réel mesuré (pas de vrais `.pak` BG3 accessibles dans l'environnement de dev utilisé) — intégration vérifiée de bout en bout sur un `.pak` synthétique

### 12. Release standalone

- **12a.** Packaging wheel Python indépendant du mod
- **12b.** GUI Python cross-platform (Linux + Windows) reprenant les fonctionnalités ci-dessus
- **12c.** Alternative serveur web local : visualisation par navigateur, échange .pak/profils par socket sécurisé (clé + fichier auth type SSH)

### 13. Licence

- ~~**13a.** Identifier et citer les licences des outils/inspirations utilisés~~ — fait : `THIRD_PARTY_LICENSES.md` (dépendances Python via PyPI, LSLib/BG3SE/BG3 Mod Manager/BG3 Compatibility Framework/Native Mod Loader via l'API GitHub, licences vérifiées à la source) + mention dans le README ; deux cas non tranchables documentés tels quels (Para Tool : aucune licence détectée sur le dépôt ; Mod Fixer et MoreReactiveCompanions : pages Nexus Mods non accessibles en automatisé — HTTP 403 — usage sous conditions Nexus par défaut)

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
- `pak_reader.PakArchive.find_suffix` retournait le PREMIER `meta.lsx` trouvé dans la table de fichiers du .pak, pas forcément le bon : un vrai .pak ("KrynnspaceCoreLibrary") embarque aussi `.../GUI/meta.lsx` (config sans rapport, coïncidence de nom) en plus du vrai descripteur `.../meta.lsx` — le mauvais était pris, donc son UUID/Name n'étaient jamais lus, et le mod (pourtant bien déployé) apparaissait à tort "manquant" partout où l'identité d'un .pak est vérifiée (dépendances, archives orphelines, origine des .pak isolés...). Corrigé : préfère désormais le chemin le plus court parmi les candidats (le vrai descripteur est toujours à la racine `Mods/<Dossier>/`, jamais plus profond)
- fork local de Mod Fixer avec meta.lsx propre (remplace ModFixer.pak, backup dans ModFixer.pak.orig, UUID stable entre reconstructions)
- `NexusFileSelectionScreen` présélectionne automatiquement les variantes UT (Unique Tav) + EOTB (Eye of the Beholder) au lieu de tout cocher par défaut, pour les mods publiant des fichiers Simple/UT/EOTB/UT+EOTB mutuellement exclusifs (ex: les collections "Mantis'...") — Elwingh a les deux mods installés et avait par erreur validé plusieurs variantes incompatibles à la fois faute de tout décocher à la main ; nouveau module pur et testé `nexus_variant_selection.infer_ut_eotb_preselection` (préfère la variante combinée si elle existe, sinon UT+EOTB séparés)
- `run_orphaned_archives`, `run_resolve_pak_origins` et `run_check_dependencies` passaient `reference_path=self._config.project_root` à `_run_divine` (repli Divine.exe) au lieu de `self._config.appdata_path` — `find_proton_prefix` remonte les dossiers PARENTS du chemin donné pour trouver le `pfx` Proton, et `project_root` (le dossier BG3Tools lui-même) n'a jamais ce préfixe dans ses parents : le repli Divine.exe échouait donc TOUJOURS avec "Impossible de déterminer le préfixe Proton de BG3", même quand Divine.exe et le préfixe existaient bien (repéré par Elwingh sur `ModFixer.pak`, qui n'a pas de meta.lsx et déclenche donc systématiquement ce repli). Corrigé aux 4 emplacements concernés
- Nouveau bouton "Vérifier les dépendances..." : lit le nœud `Dependencies` du `meta.lsx` de chaque .pak déployé (natif, repli Divine.exe) et signale celles sans mod correspondant dans Mods/ (modules vanilla — Gustav/Shared/... — ignorés, catalogue repris de `Tools/BG3-Load-Order-Optimizer/.../Bg3SystemModules.cs`) — rapport `mod_dependencies.md` sous le profil actif. Volontairement SANS détection d'incompatibilités (décision explicite d'Elwingh : pas de champ structuré pour ça dans meta.lsx, contrairement aux dépendances — scraper les pages Nexus serait fragile et limite côté ToS). Chaque dépendance manquante affiche "vu chez N mod(s)" (`mod_dependencies.count_dependency_declarations`) : un nombre élevé trahit un module système ajouté en bloc par l'outil d'export de l'auteur plutôt qu'un vrai prérequis — vérifié en conditions réelles sur les 95 .pak déployés (13 mods signalés, dont 11 pur bruit `MainUI`/`PhotoMode`/`DiceSet_*`/etc. vus chez 6 à 12 mods, et 2 cas réels à 1-2 mods : "Mod Configuration Menu" manquant pour "Hunted - Dynamic Ambushes", "KrynnspaceCoreLibrary" manquant pour les 2 mods Krynnspace)
