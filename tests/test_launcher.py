"""Tests pour bg3_mod_tui.launcher."""

from __future__ import annotations

import subprocess

import pytest

from bg3_mod_tui import launcher


class _FakePopen:
    calls: list[tuple[tuple, dict]] = []

    def __init__(self, args, **kwargs):
        _FakePopen.calls.append((tuple(args), kwargs))


@pytest.fixture(autouse=True)
def _reset_fake_popen(monkeypatch):
    _FakePopen.calls = []
    monkeypatch.setattr(launcher.subprocess, "Popen", _FakePopen)
    yield


def test_popen_detached_no_log_file(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "is_windows", lambda: False)
    launcher._popen_detached(["echo", "hi"], cwd=str(tmp_path))
    args, kwargs = _FakePopen.calls[0]
    assert args == ("echo", "hi")
    assert kwargs["stdout"] == subprocess.DEVNULL
    assert kwargs["start_new_session"] is True


def test_popen_detached_with_log_file(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "is_windows", lambda: False)
    log_file = tmp_path / "logs" / "tool.log"
    launcher._popen_detached(["echo"], cwd=str(tmp_path), log_file=log_file)
    assert log_file.parent.is_dir()
    _, kwargs = _FakePopen.calls[0]
    assert kwargs["stdout"].name == str(log_file)


def test_popen_detached_windows_flags(monkeypatch, tmp_path):
    # `CREATE_NEW_PROCESS_GROUP`/`DETACHED_PROCESS` n'existent que sous
    # Windows ; on les simule pour exercer la branche sous Linux.
    monkeypatch.setattr(launcher, "is_windows", lambda: True)
    monkeypatch.setattr(launcher.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(launcher.subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    launcher._popen_detached(["tool.exe"], cwd=str(tmp_path))
    _, kwargs = _FakePopen.calls[0]
    assert "creationflags" in kwargs
    assert "start_new_session" not in kwargs


def test_resolve_wine_bin_uses_proton_wine(monkeypatch, tmp_path):
    proton_wine = tmp_path / "proton_wine"
    monkeypatch.setattr(launcher, "find_proton_wine_bin", lambda p: proton_wine)
    assert launcher.resolve_wine_bin(tmp_path) == str(proton_wine)


def test_resolve_wine_bin_falls_back_to_system_wine(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "find_proton_wine_bin", lambda p: None)
    monkeypatch.setattr(
        launcher.shutil, "which", lambda name: "/usr/bin/wine" if name == "wine" else None
    )
    assert launcher.resolve_wine_bin(tmp_path) == "/usr/bin/wine"


def test_resolve_wine_bin_raises_if_none_found(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "find_proton_wine_bin", lambda p: None)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    with pytest.raises(launcher.LauncherError):
        launcher.resolve_wine_bin(tmp_path)


def test_launch_tool_missing_exe(tmp_path):
    with pytest.raises(launcher.LauncherError):
        launcher.launch_tool(tmp_path / "missing.exe", reference_path=tmp_path)


def test_launch_tool_windows(monkeypatch, tmp_path):
    exe = tmp_path / "tool.exe"
    exe.write_text("")
    monkeypatch.setattr(launcher, "is_windows", lambda: True)
    monkeypatch.setattr(launcher.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(launcher.subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    launcher.launch_tool(exe, reference_path=tmp_path)
    args, kwargs = _FakePopen.calls[0]
    assert args == (str(exe),)


def test_launch_tool_linux_no_proton_prefix(monkeypatch, tmp_path):
    exe = tmp_path / "tool.exe"
    exe.write_text("")
    monkeypatch.setattr(launcher, "is_windows", lambda: False)
    monkeypatch.setattr(launcher, "find_proton_prefix", lambda p: None)
    with pytest.raises(launcher.LauncherError):
        launcher.launch_tool(exe, reference_path=tmp_path)


def test_launch_tool_linux_success(monkeypatch, tmp_path):
    exe = tmp_path / "tool.exe"
    exe.write_text("")
    prefix = tmp_path / "pfx"
    monkeypatch.setattr(launcher, "is_windows", lambda: False)
    monkeypatch.setattr(launcher, "find_proton_prefix", lambda p: prefix)
    monkeypatch.setattr(launcher, "resolve_wine_bin", lambda p: "/usr/bin/wine")
    log_dir = tmp_path / "logs"
    launcher.launch_tool(exe, reference_path=tmp_path, log_dir=log_dir)
    args, kwargs = _FakePopen.calls[0]
    assert args == ("/usr/bin/wine", str(exe))
    assert kwargs["env"]["WINEPREFIX"] == str(prefix)


def test_open_protontricks_windows_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "is_windows", lambda: True)
    with pytest.raises(launcher.LauncherError):
        launcher.open_protontricks(tmp_path)


def test_open_protontricks_no_prefix(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "is_windows", lambda: False)
    monkeypatch.setattr(launcher, "find_proton_prefix", lambda p: None)
    with pytest.raises(launcher.LauncherError):
        launcher.open_protontricks(tmp_path)


def test_open_protontricks_bad_appid(monkeypatch, tmp_path):
    prefix = tmp_path / "compatdata" / "notanumber" / "pfx"
    monkeypatch.setattr(launcher, "is_windows", lambda: False)
    monkeypatch.setattr(launcher, "find_proton_prefix", lambda p: prefix)
    with pytest.raises(launcher.LauncherError):
        launcher.open_protontricks(tmp_path)


def test_open_protontricks_missing_binary(monkeypatch, tmp_path):
    prefix = tmp_path / "compatdata" / "1234" / "pfx"
    monkeypatch.setattr(launcher, "is_windows", lambda: False)
    monkeypatch.setattr(launcher, "find_proton_prefix", lambda p: prefix)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    with pytest.raises(launcher.LauncherError):
        launcher.open_protontricks(tmp_path)


def test_open_protontricks_success(monkeypatch, tmp_path):
    prefix = tmp_path / "compatdata" / "1234" / "pfx"
    monkeypatch.setattr(launcher, "is_windows", lambda: False)
    monkeypatch.setattr(launcher, "find_proton_prefix", lambda p: prefix)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "/usr/bin/protontricks")
    launcher.open_protontricks(tmp_path, log_dir=tmp_path / "logs")
    args, kwargs = _FakePopen.calls[0]
    assert args == ("/usr/bin/protontricks", "--gui", "1234")
    assert kwargs["cwd"] == str(prefix)
