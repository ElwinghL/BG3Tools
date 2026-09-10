"""Tests du rapport incrémental d'archives orphelines
(`bg3_mod_tui.screens.actions`, `run_orphaned_archives`) : la partie
formatage/écriture est une fonction pure (`_orphan_report_row`) et une
méthode qui n'utilise pas `self` (`_flush_orphans_progress`, appelée sans
instance), toutes deux testables sans app Textual ni Divine.exe.

Le reste de `run_orphaned_archives` (boucle appelant `archive_pak_identities`
via Divine.exe, thread `@work`, logs `call_from_thread`) est fortement
couplé à l'UI Textual et à un binaire externe — pas raisonnablement
extractible en fonction pure, donc pas testé ici."""

from __future__ import annotations

from pathlib import Path

from bg3_mod_tui.screens.actions import ActionsScreen, _orphan_report_row


def _archive(**overrides) -> dict:
    base = {
        "file": "MonMod_installee.zip",
        "size_bytes": 2 * 1024 * 1024,
        "mod_name_guess": "Mon Mod",
        "nexus_url": None,
        "modified": "2026-01-15T10:00:00",
    }
    base.update(overrides)
    return base


def test_orphan_report_row_format() -> None:
    row = _orphan_report_row(_archive(), "orpheline confirmée (UUID absent des .pak déployés)")
    assert row == (
        "| MonMod_installee.zip | 2.0 Mo | Mon Mod | 2026-01-15 | "
        "orpheline confirmée (UUID absent des .pak déployés) |"
    )


def test_orphan_report_row_with_nexus_url() -> None:
    row = _orphan_report_row(
        _archive(nexus_url="https://www.nexusmods.com/baldursgate3/mods/123"),
        "faux positif écarté (mod toujours déployé)",
    )
    assert "[Mon Mod](https://www.nexusmods.com/baldursgate3/mods/123)" in row
    assert row.endswith("| faux positif écarté (mod toujours déployé) |")


def test_orphan_report_row_unknown_origin() -> None:
    row = _orphan_report_row(_archive(mod_name_guess=None), "non vérifiable (pas de .pak dans l'archive)")
    assert "| ? |" in row


def test_flush_orphans_progress_writes_partial_report(tmp_path: Path) -> None:
    """Simule une interruption après 2 archives sur 5 : le rapport doit
    déjà contenir les 2 lignes traitées, avec leur statut, sans attendre
    la fin de la boucle — c'est tout l'objet de l'écriture incrémentale."""
    report_path = tmp_path / "archives_orphelines.md"
    processed = [
        (_archive(file="A_installee.zip"), "orpheline confirmée (UUID absent des .pak déployés)"),
        (_archive(file="B_installee.zip"), "faux positif écarté (mod toujours déployé)"),
    ]

    # `_flush_orphans_progress` n'utilise pas `self` : appelée directement
    # sur la classe, sans instancier `ActionsScreen` (qui requiert une app
    # Textual en cours d'exécution).
    ActionsScreen._flush_orphans_progress(
        None, report_path, processed, done=2, total=5
    )

    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "2/5 archive(s) traitée(s)" in content
    assert "A_installee.zip" in content
    assert "orpheline confirmée" in content
    assert "B_installee.zip" in content
    assert "faux positif écarté" in content
    # Rapport écrit dans un dossier pas encore créé : la méthode doit le créer.
    assert report_path.parent.is_dir()


def test_flush_orphans_progress_creates_missing_parent_dir(tmp_path: Path) -> None:
    report_path = tmp_path / "nested" / "profile" / "archives_orphelines.md"
    ActionsScreen._flush_orphans_progress(None, report_path, [], done=0, total=3)
    assert report_path.exists()
    assert "0/3 archive(s) traitée(s)" in report_path.read_text(encoding="utf-8")
