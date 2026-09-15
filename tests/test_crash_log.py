"""Tests pour bg3_mod_tui.crash_log."""

from __future__ import annotations

from bg3_mod_tui import crash_log


def test_log_crash_writes_traceback(tmp_path, monkeypatch):
    log_path = tmp_path / "crash.log"
    monkeypatch.setattr(crash_log, "CRASH_LOG_PATH", log_path)
    try:
        raise ValueError("boom")
    except ValueError as exc:
        crash_log.log_crash(exc)
    content = log_path.read_text()
    assert "boom" in content
    assert "ValueError" in content


def test_log_crash_appends_multiple_entries(tmp_path, monkeypatch):
    log_path = tmp_path / "crash.log"
    monkeypatch.setattr(crash_log, "CRASH_LOG_PATH", log_path)
    for msg in ("first", "second"):
        try:
            raise RuntimeError(msg)
        except RuntimeError as exc:
            crash_log.log_crash(exc)
    content = log_path.read_text()
    assert "first" in content
    assert "second" in content


def test_log_crash_swallows_oserror(monkeypatch, tmp_path):
    # Un dossier parent inexistant fait échouer l'ouverture en écriture
    # (`OSError`) : `log_crash` ne doit jamais lever, un plantage lors de la
    # journalisation d'un autre plantage serait pire que l'absence de log.
    bad_path = tmp_path / "missing_dir" / "crash.log"
    monkeypatch.setattr(crash_log, "CRASH_LOG_PATH", bad_path)
    try:
        raise ValueError("boom")
    except ValueError as exc:
        crash_log.log_crash(exc)  # ne lève pas
    assert not bad_path.exists()
