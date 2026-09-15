# Instructions projet — BG3Tools

## Tenue à jour de `.claude/TODO.md`

Avant de commencer toute tâche sur ce projet (correction de bug, nouvelle
fonctionnalité, investigation, chantier de sous-agent...), consulter
`.claude/TODO.md` et vérifier que la rubrique concernée reflète bien l'état
réel du code — pas seulement la rubrique visée par la tâche du jour, mais
l'ensemble des rubriques (P0 à P4, "Coordination", "Fait") si un doute
existe sur leur fraîcheur.

Avant de considérer une tâche terminée, mettre à jour `.claude/TODO.md` en
conséquence :

- rayer (`~~texte~~`) et annoter "— fait : ..." les points traités, avec un
  résumé de la cause racine et du correctif (pas juste "fait") ;
- ajouter toute découverte non prévue (bug annexe, limite technique,
  décision prise) dans la rubrique la plus proche plutôt que de la laisser
  seulement dans l'historique git ;
- tenir à jour la section "Coordination — chantiers en cours (sous-agents)"
  en haut du fichier : ajouter une entrée "EN COURS" avant de démarrer un
  chantier de sous-agent, la retirer ou la basculer en "Terminé récemment"
  une fois mergée — ne pas laisser un worktree/une branche active sans
  entrée correspondante (cf. l'incident du 2026-09-15 où le worktree
  `fix/PakEntrySizeZeroBug` avait disparu du registre alors que du travail
  non commité y était toujours en cours).

Objectif : que `.claude/TODO.md` reste la source de vérité unique et fiable
de l'avancement du projet, exploitable par n'importe quelle session/agent
sans avoir à reconstituer l'état réel depuis l'historique git ou une
conversation précédente.

## Couverture de tests

La CI n'impose qu'un seuil **global** de 75% (`fail_under` dans
`[tool.coverage.report]`, `pyproject.toml` — `coverage.py`/`pytest-cov` n'a
pas de notion de seuil par fichier nativement). Au-delà de ce plancher
imposé, tout agent ajoutant ou modifiant un fichier Python dans
`bg3_mod_tui/` doit viser **75% de couverture sur ce fichier lui-même**, pas
seulement sur la moyenne globale du projet — un fichier neuf à 30% qui
"passe" seulement parce que d'autres fichiers compensent n'est pas
acceptable. Vérifier avec `uv run pytest --cov=bg3_mod_tui
--cov-report=term-missing` et regarder la ligne du fichier concerné avant
de considérer une tâche terminée.
