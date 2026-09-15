"""Tests pour bg3_mod_tui.mod_fixer_fork.build_fork.

Divine.exe n'est jamais réellement invoqué : `_run_divine` est monkeypatché
pour simuler la création du .pak (le vrai empaquetage est déjà couvert
côté LSLib/Divine, pas de notre ressort ici) -- ces tests vérifient la
logique propre à ce module (résolution des chemins, garde-fous, sauvegarde
de l'original)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bg3_mod_tui import mod_fixer_fork as mff


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    root = tmp_path / "Tools" / "ModFixer"
    (root / "Mods" / "ModFixerFork" / "Story" / "RawFiles" / "Goals").mkdir(parents=True)
    return root.parent  # tools_dir


@pytest.fixture
def mods_dir(tmp_path: Path) -> Path:
    d = tmp_path / "Mods"
    d.mkdir()
    return d


def _patch_divine_ok(monkeypatch: pytest.MonkeyPatch, dest_pak: Path) -> list[tuple]:
    calls: list[tuple] = []

    def fake_find_divine_exe(_tools_dir: Path) -> Path:
        return Path("/fake/Divine.exe")

    def fake_run_divine(divine_exe, action, extra_args, *, reference_path):
        calls.append((action, extra_args))
        # Simule l'empaquetage réussi en créant le fichier de destination.
        dest_pak.write_bytes(b"fake-pak-content")

    monkeypatch.setattr(mff, "find_divine_exe", fake_find_divine_exe)
    monkeypatch.setattr(mff, "_run_divine", fake_run_divine)
    return calls


def test_build_fork_missing_submodule_raises(mods_dir: Path, tmp_path: Path) -> None:
    empty_tools_dir = tmp_path / "empty_tools"
    empty_tools_dir.mkdir()

    with pytest.raises(mff.ModFixerForkError, match="Tools/ModFixer"):
        mff.build_fork(mods_dir, empty_tools_dir, reference_path=tmp_path)


def test_build_fork_missing_divine_raises(
    mods_dir: Path, source_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mff, "find_divine_exe", lambda _tools_dir: None)

    with pytest.raises(mff.ModFixerForkError, match="Divine.exe"):
        mff.build_fork(mods_dir, source_root, reference_path=source_root)


def test_build_fork_packages_from_submodule(
    mods_dir: Path, source_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_pak = mods_dir / mff.ORIGINAL_PAK_NAME
    calls = _patch_divine_ok(monkeypatch, dest_pak)

    logs: list[str] = []
    result = mff.build_fork(mods_dir, source_root, reference_path=source_root, log=logs.append)

    assert result == dest_pak
    assert dest_pak.is_file()
    assert not (mods_dir / mff.ORIGINAL_BACKUP_NAME).exists()

    assert len(calls) == 1
    action, extra_args = calls[0]
    assert action == "create-package"
    assert extra_args[0] == "-s"
    assert "ModFixer" in extra_args[1]
    assert extra_args[2] == "-d"
    assert mff.ORIGINAL_PAK_NAME in extra_args[3]
    assert any("Empaquetage" in line for line in logs)


def test_build_fork_backs_up_existing_pak_once(
    mods_dir: Path, source_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dest_pak = mods_dir / mff.ORIGINAL_PAK_NAME
    backup_pak = mods_dir / mff.ORIGINAL_BACKUP_NAME
    dest_pak.write_bytes(b"original-user-installed-pak")

    _patch_divine_ok(monkeypatch, dest_pak)

    mff.build_fork(mods_dir, source_root, reference_path=source_root)

    assert backup_pak.is_file()
    assert backup_pak.read_bytes() == b"original-user-installed-pak"

    # Rebuild : ne doit PAS re-sauvegarder par-dessus (backup déjà pris une
    # fois pour toutes, avant la première réécriture).
    dest_pak.write_bytes(b"our-first-fork-build")
    mff.build_fork(mods_dir, source_root, reference_path=source_root)

    assert backup_pak.read_bytes() == b"original-user-installed-pak"


def test_divine_command_on_windows_has_no_wine_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mff, "is_windows", lambda: True)

    command, env = mff._divine_command(
        Path("Divine.exe"), "list-package", ["-s", "x"], reference_path=Path("/tmp")
    )

    assert command == ["Divine.exe", "-g", "bg3", "-a", "list-package", "-s", "x"]
    assert env is None


def test_divine_command_on_linux_sets_wineprefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mff, "is_windows", lambda: False)
    monkeypatch.setattr(mff, "find_proton_prefix", lambda _ref: Path("/fake/prefix"))
    monkeypatch.setattr(mff, "resolve_wine_bin", lambda _prefix: "/usr/bin/wine")

    command, env = mff._divine_command(
        Path("/tools/Divine.exe"), "create-package", ["-s", "x"], reference_path=Path("/tmp")
    )

    assert command[0] == "/usr/bin/wine"
    assert env is not None
    assert env["WINEPREFIX"] == str(Path("/fake/prefix"))


def test_divine_command_on_linux_without_prefix_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mff, "is_windows", lambda: False)
    monkeypatch.setattr(mff, "find_proton_prefix", lambda _ref: None)

    with pytest.raises(mff.ModFixerForkError, match="préfixe Proton"):
        mff._divine_command(Path("Divine.exe"), "create-package", [], reference_path=Path("/tmp"))


def test_run_divine_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeResult:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(mff, "is_windows", lambda: True)
    monkeypatch.setattr(mff.subprocess, "run", lambda *a, **kw: _FakeResult())

    with pytest.raises(mff.ModFixerForkError, match="boom"):
        mff._run_divine(Path("Divine.exe"), "create-package", [], reference_path=Path("/tmp"))


def test_run_divine_raises_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess as _subprocess

    monkeypatch.setattr(mff, "is_windows", lambda: True)

    def _raise_timeout(*_a, **_kw):
        raise _subprocess.TimeoutExpired(cmd="Divine.exe", timeout=60)

    monkeypatch.setattr(mff.subprocess, "run", _raise_timeout)

    with pytest.raises(mff.ModFixerForkError, match="Timeout"):
        mff._run_divine(Path("Divine.exe"), "create-package", [], reference_path=Path("/tmp"))


def test_build_fork_raises_if_pak_not_produced(
    mods_dir: Path, source_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mff, "find_divine_exe", lambda _tools_dir: Path("/fake/Divine.exe"))
    monkeypatch.setattr(mff, "_run_divine", lambda *a, **kw: None)  # ne crée rien

    with pytest.raises(mff.ModFixerForkError, match="Échec de l'empaquetage"):
        mff.build_fork(mods_dir, source_root, reference_path=source_root)
