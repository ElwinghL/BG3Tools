"""Tests pour bg3_mod_tui/compat_framework.py — construction du .pak de
BG3 Compatibility Framework via Divine.exe. `subprocess.run` (Divine.exe)
n'est jamais réellement invoqué."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bg3_mod_tui import compat_framework as cf


@pytest.fixture
def tools_dir(tmp_path: Path) -> Path:
    root = tmp_path / "Tools" / cf.TOOL_LOCAL_DIR_NAME / cf._SOURCE_SUBDIR
    (root / "Mods").mkdir(parents=True)
    return tmp_path / "Tools"


@pytest.fixture
def mods_dir(tmp_path: Path) -> Path:
    return tmp_path / "Mods"


def _add_divine(tools_dir: Path) -> Path:
    divine = tools_dir / "ExportTools" / "Packed" / "Tools" / "Divine.exe"
    divine.parent.mkdir(parents=True)
    divine.write_bytes(b"")
    return divine


# ---------------------------------------------------------------------------
# find_divine_exe / find_source_root
# ---------------------------------------------------------------------------


def test_find_divine_exe_missing(tmp_path):
    assert cf.find_divine_exe(tmp_path) is None


def test_find_divine_exe_found(tools_dir):
    divine = _add_divine(tools_dir)
    assert cf.find_divine_exe(tools_dir) == divine


def test_find_source_root_missing(tmp_path):
    assert cf.find_source_root(tmp_path) is None


def test_find_source_root_found(tools_dir):
    expected = tools_dir / cf.TOOL_LOCAL_DIR_NAME / cf._SOURCE_SUBDIR
    assert cf.find_source_root(tools_dir) == expected


# ---------------------------------------------------------------------------
# build_pak
# ---------------------------------------------------------------------------


def test_build_pak_missing_sources_raises(tmp_path, mods_dir):
    empty_tools_dir = tmp_path / "empty"
    empty_tools_dir.mkdir()
    with pytest.raises(cf.CompatibilityFrameworkError, match="Sources introuvables"):
        cf.build_pak(empty_tools_dir, mods_dir, reference_path=tmp_path)


def test_build_pak_missing_divine_raises(tools_dir, mods_dir):
    with pytest.raises(cf.CompatibilityFrameworkError, match="Divine.exe introuvable"):
        cf.build_pak(tools_dir, mods_dir, reference_path=tools_dir)


def test_build_pak_windows_success(tools_dir, mods_dir, monkeypatch):
    _add_divine(tools_dir)
    monkeypatch.setattr(cf, "is_windows", lambda: True)

    def fake_run(command, **kwargs):
        dest = Path(command[command.index("--destination") + 1])
        dest.write_bytes(b"fake-pak")
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cf.subprocess, "run", fake_run)

    logs = []
    result = cf.build_pak(tools_dir, mods_dir, reference_path=tools_dir, log=logs.append)

    assert result == mods_dir / cf.PAK_NAME
    assert result.is_file()
    assert any("créé" in m for m in logs)


def test_build_pak_linux_without_proton_prefix_raises(tools_dir, mods_dir, monkeypatch):
    _add_divine(tools_dir)
    monkeypatch.setattr(cf, "is_windows", lambda: False)
    monkeypatch.setattr(cf, "find_proton_prefix", lambda _ref: None)

    with pytest.raises(cf.CompatibilityFrameworkError, match="préfixe Proton"):
        cf.build_pak(tools_dir, mods_dir, reference_path=tools_dir)


def test_build_pak_linux_success_sets_wineprefix(tools_dir, mods_dir, monkeypatch):
    _add_divine(tools_dir)
    monkeypatch.setattr(cf, "is_windows", lambda: False)
    monkeypatch.setattr(cf, "find_proton_prefix", lambda _ref: Path("/fake/prefix"))
    monkeypatch.setattr(cf, "resolve_wine_bin", lambda _prefix: "/usr/bin/wine")
    monkeypatch.setattr(cf, "to_wine_path", lambda p: f"Z:{p}")

    captured = {}

    def fake_run(command, env=None, **kwargs):
        captured["command"] = command
        captured["env"] = env
        (mods_dir / cf.PAK_NAME).write_bytes(b"fake-pak")
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cf.subprocess, "run", fake_run)

    result = cf.build_pak(tools_dir, mods_dir, reference_path=tools_dir)

    assert result.is_file()
    assert captured["command"][0] == "/usr/bin/wine"
    assert captured["env"]["WINEPREFIX"] == str(Path("/fake/prefix"))


def test_build_pak_timeout_raises(tools_dir, mods_dir, monkeypatch):
    _add_divine(tools_dir)
    monkeypatch.setattr(cf, "is_windows", lambda: True)

    def fake_run(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="Divine.exe", timeout=120)

    monkeypatch.setattr(cf.subprocess, "run", fake_run)

    with pytest.raises(cf.CompatibilityFrameworkError, match="Timeout"):
        cf.build_pak(tools_dir, mods_dir, reference_path=tools_dir)


def test_build_pak_oserror_raises(tools_dir, mods_dir, monkeypatch):
    _add_divine(tools_dir)
    monkeypatch.setattr(cf, "is_windows", lambda: True)

    def fake_run(*a, **kw):
        raise OSError("binaire introuvable")

    monkeypatch.setattr(cf.subprocess, "run", fake_run)

    with pytest.raises(cf.CompatibilityFrameworkError, match="Échec du lancement"):
        cf.build_pak(tools_dir, mods_dir, reference_path=tools_dir)


def test_build_pak_nonzero_exit_raises(tools_dir, mods_dir, monkeypatch):
    _add_divine(tools_dir)
    monkeypatch.setattr(cf, "is_windows", lambda: True)
    monkeypatch.setattr(
        cf.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="échec divine"
        ),
    )

    with pytest.raises(cf.CompatibilityFrameworkError, match="échec divine"):
        cf.build_pak(tools_dir, mods_dir, reference_path=tools_dir)


def test_build_pak_success_but_no_file_produced_raises(tools_dir, mods_dir, monkeypatch):
    _add_divine(tools_dir)
    monkeypatch.setattr(cf, "is_windows", lambda: True)
    monkeypatch.setattr(
        cf.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(cf.CompatibilityFrameworkError, match="Échec de l'empaquetage"):
        cf.build_pak(tools_dir, mods_dir, reference_path=tools_dir)
