"""Tests pour bg3_mod_tui.wineprefix."""

from __future__ import annotations

import subprocess

import pytest

from bg3_mod_tui import wineprefix as wp


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_wine_reg_success(monkeypatch, tmp_path):
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: _completed())
    result = wp._run_wine_reg("wine", tmp_path, ["query", "HKCU"])
    assert result.returncode == 0


def test_run_wine_reg_timeout(monkeypatch, tmp_path):
    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="wine", timeout=30)

    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    with pytest.raises(wp.WinePrefixError, match="Timeout"):
        wp._run_wine_reg("wine", tmp_path, ["query"])


def test_run_wine_reg_oserror(monkeypatch, tmp_path):
    def fake_run(*a, **k):
        raise OSError("no such binary")

    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    with pytest.raises(wp.WinePrefixError, match="Échec"):
        wp._run_wine_reg("wine", tmp_path, ["query"])


def test_set_app_windows_version_success(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "_run_wine_reg", lambda *a, **k: _completed(0))
    wp.set_app_windows_version("wine", tmp_path, "Tool.exe")  # ne lève pas


def test_set_app_windows_version_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "_run_wine_reg", lambda *a, **k: _completed(1, stderr="boom"))
    with pytest.raises(wp.WinePrefixError, match="Tool.exe"):
        wp.set_app_windows_version("wine", tmp_path, "Tool.exe")


def test_clear_global_override_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "_run_wine_reg", lambda *a, **k: _completed(1))
    assert wp.clear_global_windows_version_override("wine", tmp_path) is False


def test_clear_global_override_removed(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return _completed(0)

    monkeypatch.setattr(wp, "_run_wine_reg", fake)
    assert wp.clear_global_windows_version_override("wine", tmp_path) is True
    assert calls["n"] == 2


def test_clear_global_override_delete_fails(monkeypatch, tmp_path):
    responses = [_completed(0), _completed(1, stderr="denied")]

    def fake(*a, **k):
        return responses.pop(0)

    monkeypatch.setattr(wp, "_run_wine_reg", fake)
    with pytest.raises(wp.WinePrefixError, match="global"):
        wp.clear_global_windows_version_override("wine", tmp_path)


def test_run_winetricks_verbs_missing_binary(monkeypatch):
    monkeypatch.setattr(wp.shutil, "which", lambda name: None)
    with pytest.raises(wp.WinePrefixError, match="protontricks"):
        wp.run_winetricks_verbs("1234", ["vcrun2022"])


def test_run_winetricks_verbs_timeout(monkeypatch):
    monkeypatch.setattr(wp.shutil, "which", lambda name: "/usr/bin/protontricks")

    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="protontricks", timeout=900)

    monkeypatch.setattr(wp.subprocess, "run", fake_run)
    with pytest.raises(wp.WinePrefixError, match="Timeout"):
        wp.run_winetricks_verbs("1234", ["vcrun2022"])


def test_run_winetricks_verbs_failure_with_log(monkeypatch, tmp_path):
    monkeypatch.setattr(wp.shutil, "which", lambda name: "/usr/bin/protontricks")
    monkeypatch.setattr(
        wp.subprocess, "run", lambda *a, **k: _completed(1, stdout="out", stderr="err")
    )
    log_dir = tmp_path / "logs"
    with pytest.raises(wp.WinePrefixError, match="Échec"):
        wp.run_winetricks_verbs("1234", ["vcrun2022"], log_dir=log_dir)
    log_file = log_dir / "protontricks.log"
    assert log_file.is_file()
    assert "err" in log_file.read_text()


def test_run_winetricks_verbs_success(monkeypatch):
    monkeypatch.setattr(wp.shutil, "which", lambda name: "/usr/bin/protontricks")
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: _completed(0))
    wp.run_winetricks_verbs("1234", ["vcrun2022"])  # ne lève pas


def test_optimize_prefix_for_tools_full_flow(monkeypatch, tmp_path):
    logs: list[str] = []
    monkeypatch.setattr(wp, "run_winetricks_verbs", lambda *a, **k: None)
    monkeypatch.setattr(wp, "set_app_windows_version", lambda *a, **k: None)
    monkeypatch.setattr(wp, "clear_global_windows_version_override", lambda *a, **k: True)

    tool = tmp_path / "Tool.exe"
    wp.optimize_prefix_for_tools(
        appid="1234",
        wine_bin="wine",
        prefix=tmp_path / "pfx",
        tool_executables=[tool],
        log=logs.append,
    )
    assert any("résiduel" in msg for msg in logs)
    assert any("Tool.exe" in msg for msg in logs)


def test_optimize_prefix_for_tools_no_verbs_and_clean_prefix(monkeypatch, tmp_path):
    logs: list[str] = []
    called = {"winetricks": False}

    def fake_winetricks(*a, **k):
        called["winetricks"] = True

    monkeypatch.setattr(wp, "run_winetricks_verbs", fake_winetricks)
    monkeypatch.setattr(wp, "set_app_windows_version", lambda *a, **k: None)
    monkeypatch.setattr(wp, "clear_global_windows_version_override", lambda *a, **k: False)

    wp.optimize_prefix_for_tools(
        appid="1234",
        wine_bin="wine",
        prefix=tmp_path / "pfx",
        tool_executables=[],
        verbs=[],
        log=logs.append,
    )
    assert called["winetricks"] is False
    assert any("propre" in msg for msg in logs)
