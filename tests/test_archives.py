"""Tests pour bg3_mod_tui/archives.py — extraction d'archives .zip/.rar/.7z.
Tout appel à `unrar`/`7z` (subprocess) est mocké ; seule l'extraction .zip
(module standard `zipfile`) est exercée avec une vraie archive de test."""

from __future__ import annotations

import subprocess
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from bg3_mod_tui import archives


# ---------------------------------------------------------------------------
# is_supported_archive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["mod.zip", "mod.ZIP", "mod.rar", "mod.7z"])
def test_is_supported_archive_true(tmp_path, name):
    assert archives.is_supported_archive(tmp_path / name) is True


@pytest.mark.parametrize("name", ["mod.txt", "mod.tar.gz", "mod"])
def test_is_supported_archive_false(tmp_path, name):
    assert archives.is_supported_archive(tmp_path / name) is False


# ---------------------------------------------------------------------------
# extract_archive : .zip (réel)
# ---------------------------------------------------------------------------


def test_extract_archive_zip_real(tmp_path):
    archive = tmp_path / "mod.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("meta.lsx", "<data/>")
        zf.writestr("sub/file.txt", "hello")

    dest = tmp_path / "out"
    archives.extract_archive(archive, dest)

    assert (dest / "meta.lsx").read_text(encoding="utf-8") == "<data/>"
    assert (dest / "sub" / "file.txt").read_text(encoding="utf-8") == "hello"


def test_extract_archive_zip_bad_file_wraps_error(tmp_path):
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"not a real zip")
    dest = tmp_path / "out"
    with pytest.raises(archives.ArchiveError, match="Échec de l'extraction"):
        archives.extract_archive(archive, dest)


def test_extract_archive_unsupported_format(tmp_path):
    archive = tmp_path / "mod.tar"
    archive.write_bytes(b"")
    with pytest.raises(archives.ArchiveError, match="non supporté"):
        archives.extract_archive(archive, tmp_path / "out")


# ---------------------------------------------------------------------------
# extract_archive : .rar / .7z (binaires mockés)
# ---------------------------------------------------------------------------


def _fake_popen(returncode=0, stdout="", stderr=""):
    proc = MagicMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    return proc


def test_extract_rar_uses_unrar_when_available(tmp_path):
    archive = tmp_path / "mod.rar"
    archive.write_bytes(b"")
    dest = tmp_path / "out"

    with (
        patch.object(
            archives.shutil,
            "which",
            side_effect=lambda b: "/usr/bin/unrar" if b == "unrar" else None,
        ),
        patch.object(archives.subprocess, "Popen", return_value=_fake_popen()) as popen,
    ):
        archives.extract_archive(archive, dest)

    assert dest.is_dir()
    args = popen.call_args.args[0]
    assert args[0] == "unrar"


def test_extract_rar_falls_back_to_7z(tmp_path):
    archive = tmp_path / "mod.rar"
    archive.write_bytes(b"")
    dest = tmp_path / "out"

    with (
        patch.object(
            archives.shutil, "which", side_effect=lambda b: "/usr/bin/7z" if b == "7z" else None
        ),
        patch.object(archives.subprocess, "Popen", return_value=_fake_popen()) as popen,
    ):
        archives.extract_archive(archive, dest)

    args = popen.call_args.args[0]
    assert args[0] == "7z"


def test_extract_7z_uses_7z_binary(tmp_path):
    archive = tmp_path / "mod.7z"
    archive.write_bytes(b"")
    dest = tmp_path / "out"

    with (
        patch.object(archives.shutil, "which", return_value="/usr/bin/7z"),
        patch.object(archives.subprocess, "Popen", return_value=_fake_popen()) as popen,
    ):
        archives.extract_archive(archive, dest)

    args = popen.call_args.args[0]
    assert args[0] == "7z"


def test_extract_via_binary_missing_binary_raises(tmp_path):
    archive = tmp_path / "mod.7z"
    archive.write_bytes(b"")
    dest = tmp_path / "out"

    with patch.object(archives.shutil, "which", return_value=None):
        with pytest.raises(archives.ArchiveError, match="introuvable dans le PATH"):
            archives.extract_archive(archive, dest)


def test_extract_via_binary_nonzero_exit_raises(tmp_path):
    archive = tmp_path / "mod.7z"
    archive.write_bytes(b"")
    dest = tmp_path / "out"

    with (
        patch.object(archives.shutil, "which", return_value="/usr/bin/7z"),
        patch.object(
            archives.subprocess, "Popen", return_value=_fake_popen(returncode=2, stderr="boom")
        ),
    ):
        with pytest.raises(archives.ArchiveError, match="boom"):
            archives.extract_archive(archive, dest)


def test_extract_via_binary_nonzero_exit_uses_stdout_if_no_stderr(tmp_path):
    archive = tmp_path / "mod.7z"
    archive.write_bytes(b"")
    dest = tmp_path / "out"

    with (
        patch.object(archives.shutil, "which", return_value="/usr/bin/7z"),
        patch.object(
            archives.subprocess,
            "Popen",
            return_value=_fake_popen(returncode=1, stdout="stdout-message", stderr=""),
        ),
    ):
        with pytest.raises(archives.ArchiveError, match="stdout-message"):
            archives.extract_archive(archive, dest)


def test_extract_via_binary_registers_and_discards_active_process(tmp_path):
    archive = tmp_path / "mod.7z"
    archive.write_bytes(b"")
    dest = tmp_path / "out"

    proc = _fake_popen()
    with (
        patch.object(archives.shutil, "which", return_value="/usr/bin/7z"),
        patch.object(archives.subprocess, "Popen", return_value=proc),
    ):
        archives.extract_archive(archive, dest)

    # Le process a bien été retiré du registre après complétion.
    assert proc not in archives._active_processes


# ---------------------------------------------------------------------------
# terminate_active_extractions
# ---------------------------------------------------------------------------


def test_terminate_active_extractions_terminates_running_processes():
    running_proc = MagicMock()
    running_proc.poll.return_value = None
    running_proc.wait.return_value = None

    finished_proc = MagicMock()
    finished_proc.poll.return_value = 0

    with archives._active_processes_lock:
        archives._active_processes.add(running_proc)
        archives._active_processes.add(finished_proc)
    try:
        archives.terminate_active_extractions()
    finally:
        with archives._active_processes_lock:
            archives._active_processes.discard(running_proc)
            archives._active_processes.discard(finished_proc)

    running_proc.terminate.assert_called_once()
    finished_proc.terminate.assert_not_called()


def test_terminate_active_extractions_kills_on_timeout():
    stuck_proc = MagicMock()
    stuck_proc.poll.return_value = None
    stuck_proc.wait.side_effect = subprocess.TimeoutExpired(cmd="7z", timeout=3)

    with archives._active_processes_lock:
        archives._active_processes.add(stuck_proc)
    try:
        archives.terminate_active_extractions()
    finally:
        with archives._active_processes_lock:
            archives._active_processes.discard(stuck_proc)

    stuck_proc.kill.assert_called_once()


def test_terminate_active_extractions_noop_when_empty():
    archives.terminate_active_extractions()
