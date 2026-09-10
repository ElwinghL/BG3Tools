"""Tests du mécanisme d'onglets dynamiques pour les tâches "Tâches"
concurrentes (`bg3_mod_tui.screens.actions`, sous-tâche 7b du TODO "Vue
par onglets") : `_resource_conflict` est la seule partie de ce mécanisme
qui soit une fonction pure, testable sans app Textual — elle décide si une
nouvelle tâche peut être lancée en parallèle des tâches déjà actives, en
comparant leurs étiquettes de ressources (voir `ActionsScreen._start_task`
et le dictionnaire `_ActiveTask`).

Le reste du mécanisme (`_acquire_task_console`, `_start_task`,
`on_worker_state_changed`) est fortement couplé à l'UI Textual : il
interroge/modifie `#logs-tabs` (`TabbedContent.add_pane`, `query_one`) et
au cycle de vie des `Worker` (thread=True, `call_from_thread`), ce qui
nécessite une app Textual en cours d'exécution (event loop, DOM monté) —
pas raisonnablement extractible en fonction pure, donc pas testé ici. Un
test de bout en bout (lancer deux actions, vérifier qu'un second onglet
apparaît) relèverait plutôt d'un test Pilot Textual, hors du scope de
cette sous-tâche.

Ce fichier teste aussi `_run_task_sequence` (TODO "Fusion bouton MAJ
outils + Compat Framework + ModFixerFork", sous-tâche 9a) : la fonction
d'enchaînement/arrêt-au-premier-échec utilisée par le bouton unifié "Tout
mettre à jour", elle aussi factorisée en fonction module-level pure pour
rester testable sans app Textual — les 3 étapes qu'elle enchaîne en
pratique (`_download_tools_task` et consorts) restent, elles, couplées à
`ActionsScreen._config` et à Divine.exe/le réseau, donc non testées ici."""

from __future__ import annotations

from bg3_mod_tui.screens.actions import _resource_conflict, _run_task_sequence


def test_no_conflict_when_no_active_task() -> None:
    assert _resource_conflict([], frozenset({"mods-dir"})) == frozenset()


def test_no_conflict_when_requested_tags_empty() -> None:
    """Une action à lecture seule (resource_tags=frozenset()) ne peut
    jamais être bloquée, même si une autre tâche tient déjà toutes les
    ressources connues."""
    active = [frozenset({"mods-dir", "archives", "native-mods"})]
    assert _resource_conflict(active, frozenset()) == frozenset()


def test_no_conflict_with_disjoint_tags() -> None:
    active = [frozenset({"archives"})]
    assert _resource_conflict(active, frozenset({"mods-dir"})) == frozenset()


def test_conflict_on_shared_tag() -> None:
    active = [frozenset({"mods-dir", "modsettings"})]
    conflict = _resource_conflict(active, frozenset({"mods-dir", "tools-dir"}))
    assert conflict == frozenset({"mods-dir"})


def test_conflict_checks_across_all_active_tasks() -> None:
    """Deux tâches read-only actives (`frozenset()` chacune) plus une
    tâche qui tient "archives" : une nouvelle tâche demandant "archives"
    doit être refusée à cause de la troisième, même si les deux premières
    ne tiennent rien."""
    active = [frozenset(), frozenset(), frozenset({"archives"})]
    assert _resource_conflict(active, frozenset({"archives"})) == frozenset({"archives"})


def test_conflict_reports_every_shared_tag() -> None:
    active = [frozenset({"mods-dir"}), frozenset({"native-mods"})]
    conflict = _resource_conflict(active, frozenset({"mods-dir", "native-mods", "tools-dir"}))
    assert conflict == frozenset({"mods-dir", "native-mods"})


def test_run_task_sequence_runs_all_steps_in_order_on_success() -> None:
    calls: list[str] = []

    def make_step(name: str):
        def step(log) -> bool:
            calls.append(name)
            return True
        return step

    steps = [("un", make_step("un")), ("deux", make_step("deux")), ("trois", make_step("trois"))]
    logs: list[str] = []
    assert _run_task_sequence(steps, logs.append) is True
    assert calls == ["un", "deux", "trois"]
    # Progression [i/3] journalisée avant chaque étape.
    assert any("[1/3]" in line and "un" in line for line in logs)
    assert any("[2/3]" in line and "deux" in line for line in logs)
    assert any("[3/3]" in line and "trois" in line for line in logs)


def test_run_task_sequence_stops_at_first_failure() -> None:
    """Étape 2 échoue : l'étape 3 ne doit PAS être tentée (arrêt à la
    première erreur — voir docstring de `_run_task_sequence`, les étapes du
    bouton "Tout mettre à jour" ont des dépendances explicites entre
    elles)."""
    calls: list[str] = []

    def ok(log) -> bool:
        calls.append("ok")
        return True

    def fail(log) -> bool:
        calls.append("fail")
        return False

    def should_not_run(log) -> bool:
        calls.append("should_not_run")
        return True

    steps = [("un", ok), ("deux", fail), ("trois", should_not_run)]
    logs: list[str] = []
    assert _run_task_sequence(steps, logs.append) is False
    assert calls == ["ok", "fail"]
    assert any("échoué" in line for line in logs)


def test_run_task_sequence_empty_steps_succeeds_trivially() -> None:
    logs: list[str] = []
    assert _run_task_sequence([], logs.append) is True
