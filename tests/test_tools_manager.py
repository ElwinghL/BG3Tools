"""Tests pour bg3_mod_tui/tools_manager.py — parsing de TOOLS.md,
installation d'outils (sous-module git / release GitHub / archive Nexus
manuelle). Tout appel subprocess/httpx/filesystem réel est mocké ; aucun
accès réseau ni git réel n'est effectué."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bg3_mod_tui import tools_manager as tm


def _cp(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# parse_tools_table
# ---------------------------------------------------------------------------


def test_parse_tools_table_missing_file(tmp_path):
    with pytest.raises(tm.ToolsError):
        tm.parse_tools_table(tmp_path / "nope.md")


def test_parse_tools_table_parses_rows(tmp_path):
    md = tmp_path / "TOOLS.md"
    md.write_text(
        "\n".join(
            [
                "| Outil | Dossier local | Dépôt source |",
                "|---|---|---|",
                "| bg3rustpaklib | `Tools/bg3rustpaklib` | https://github.com/Foo/bg3rustpaklib |",
                "| ConfigApp | `Tools/ConfigApp` | https://www.nexusmods.com/baldursgate3/mods/5447 |",
                "| Manual | | pas de dépôt |",
                "not a table row at all",
            ]
        ),
        encoding="utf-8",
    )
    entries = tm.parse_tools_table(md)
    assert len(entries) == 3

    gh = entries[0]
    assert gh.name == "bg3rustpaklib"
    assert gh.local_dir == "Tools/bg3rustpaklib"
    assert gh.github_owner == "Foo"
    assert gh.github_repo == "bg3rustpaklib"
    assert gh.nexus_mod_id is None

    nexus = entries[1]
    assert nexus.name == "ConfigApp"
    assert nexus.local_dir == "Tools/ConfigApp"
    assert nexus.github_owner is None
    assert nexus.nexus_mod_id == 5447

    manual = entries[2]
    assert manual.name == "Manual"
    assert manual.local_dir is None
    assert manual.github_owner is None
    assert manual.nexus_mod_id is None


def test_parse_tools_table_strips_trailing_slash_and_skips_separator(tmp_path):
    md = tmp_path / "TOOLS.md"
    md.write_text(
        "| Outil | Dossier local | Dépôt source |\n"
        "| --- | --- | --- |\n"
        "| X | `Tools/X/` | https://github.com/A/B |\n",
        encoding="utf-8",
    )
    entries = tm.parse_tools_table(md)
    assert len(entries) == 1
    assert entries[0].local_dir == "Tools/X"


# ---------------------------------------------------------------------------
# _run_git / _is_registered_submodule
# ---------------------------------------------------------------------------


def test_run_git_invokes_subprocess(tmp_path):
    with patch.object(tm.subprocess, "run", return_value=_cp(stdout="ok")) as run:
        result = tm._run_git(["status"], cwd=tmp_path)
    run.assert_called_once()
    args, kwargs = run.call_args
    assert args[0] == ["git", "status"]
    assert kwargs["cwd"] == tmp_path
    assert result.stdout == "ok"


def test_is_registered_submodule_no_gitmodules(tmp_path):
    assert tm._is_registered_submodule(tmp_path, "Tools/X") is False


def test_is_registered_submodule_git_failure(tmp_path):
    (tmp_path / ".gitmodules").write_text("", encoding="utf-8")
    with patch.object(tm, "_run_git", return_value=_cp(returncode=1)):
        assert tm._is_registered_submodule(tmp_path, "Tools/X") is False


def test_is_registered_submodule_true(tmp_path):
    (tmp_path / ".gitmodules").write_text("", encoding="utf-8")
    with patch.object(tm, "_run_git", return_value=_cp(stdout="submodule.foo.path Tools/X\n")):
        assert tm._is_registered_submodule(tmp_path, "Tools/X") is True


def test_is_registered_submodule_false_no_match(tmp_path):
    (tmp_path / ".gitmodules").write_text("", encoding="utf-8")
    with patch.object(tm, "_run_git", return_value=_cp(stdout="submodule.foo.path Tools/Y\n")):
        assert tm._is_registered_submodule(tmp_path, "Tools/X") is False


# ---------------------------------------------------------------------------
# _add_or_update_git_submodule
# ---------------------------------------------------------------------------


def test_add_or_update_git_submodule_new(tmp_path):
    logs = []
    with (
        patch.object(tm, "_is_registered_submodule", return_value=False),
        patch.object(tm, "_run_git") as run_git,
    ):
        run_git.side_effect = [_cp(returncode=0), _cp(stdout="abc1234\n")]
        rev = tm._add_or_update_git_submodule(
            "Owner", "Repo", "Tools/Repo", tmp_path, log=logs.append
        )
    assert rev == "abc1234"
    assert any("ajout comme sous-module" in m for m in logs)
    add_call = run_git.call_args_list[0]
    assert add_call.args[0][0:2] == ["submodule", "add"]


def test_add_or_update_git_submodule_existing(tmp_path):
    logs = []
    with (
        patch.object(tm, "_is_registered_submodule", return_value=True),
        patch.object(tm, "_run_git") as run_git,
    ):
        run_git.side_effect = [_cp(returncode=0), _cp(stdout="deadbee\n")]
        rev = tm._add_or_update_git_submodule(
            "Owner", "Repo", "Tools/Repo", tmp_path, log=logs.append
        )
    assert rev == "deadbee"
    update_call = run_git.call_args_list[0]
    assert update_call.args[0][0:2] == ["submodule", "update"]


def test_add_or_update_git_submodule_add_failure(tmp_path):
    with (
        patch.object(tm, "_is_registered_submodule", return_value=False),
        patch.object(tm, "_run_git", return_value=_cp(returncode=1, stderr="boom")),
    ):
        with pytest.raises(tm.ToolsError, match="échec de 'git submodule add'"):
            tm._add_or_update_git_submodule(
                "Owner", "Repo", "Tools/Repo", tmp_path, log=lambda m: None
            )


def test_add_or_update_git_submodule_update_failure(tmp_path):
    with (
        patch.object(tm, "_is_registered_submodule", return_value=True),
        patch.object(tm, "_run_git", return_value=_cp(returncode=1, stderr="nope")),
    ):
        with pytest.raises(tm.ToolsError, match="échec de 'git submodule update'"):
            tm._add_or_update_git_submodule(
                "Owner", "Repo", "Tools/Repo", tmp_path, log=lambda m: None
            )


def test_add_or_update_git_submodule_rev_parse_failure(tmp_path):
    with (
        patch.object(tm, "_is_registered_submodule", return_value=False),
        patch.object(tm, "_run_git") as run_git,
    ):
        run_git.side_effect = [_cp(returncode=0), _cp(returncode=1, stderr="bad rev")]
        with pytest.raises(tm.ToolsError, match="impossible de lire le commit HEAD"):
            tm._add_or_update_git_submodule(
                "Owner", "Repo", "Tools/Repo", tmp_path, log=lambda m: None
            )


# ---------------------------------------------------------------------------
# _installed_version
# ---------------------------------------------------------------------------


def test_installed_version_missing(tmp_path):
    assert tm._installed_version(tmp_path) is None


def test_installed_version_present(tmp_path):
    (tmp_path / tm.VERSION_MARKER_NAME).write_text("v1.2.3\n", encoding="utf-8")
    assert tm._installed_version(tmp_path) == "v1.2.3"


def test_installed_version_empty_file(tmp_path):
    (tmp_path / tm.VERSION_MARKER_NAME).write_text("  \n", encoding="utf-8")
    assert tm._installed_version(tmp_path) is None


def test_installed_version_oserror(tmp_path):
    marker = tmp_path / tm.VERSION_MARKER_NAME
    marker.write_text("v1", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("boom")):
        assert tm._installed_version(tmp_path) is None


# ---------------------------------------------------------------------------
# _flatten_and_move
# ---------------------------------------------------------------------------


def test_flatten_and_move_single_wrapper_dir(tmp_path):
    src = tmp_path / "src"
    wrapper = src / "repo-main"
    wrapper.mkdir(parents=True)
    (wrapper / "file.txt").write_text("hello", encoding="utf-8")
    dest = tmp_path / "dest"

    tm._flatten_and_move(src, dest)

    assert (dest / "file.txt").read_text(encoding="utf-8") == "hello"


def test_flatten_and_move_multiple_top_level_entries(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a", encoding="utf-8")
    (src / "b.txt").write_text("b", encoding="utf-8")
    dest = tmp_path / "dest"

    tm._flatten_and_move(src, dest)

    assert (dest / "a.txt").read_text(encoding="utf-8") == "a"
    assert (dest / "b.txt").read_text(encoding="utf-8") == "b"


def test_flatten_and_move_overwrites_existing_file_and_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "keep.txt").write_text("new", encoding="utf-8")
    (src / "subdir").mkdir()
    (src / "subdir" / "inner.txt").write_text("new-inner", encoding="utf-8")

    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "keep.txt").write_text("old", encoding="utf-8")
    (dest / "subdir").mkdir()
    (dest / "subdir" / "stale.txt").write_text("stale", encoding="utf-8")

    tm._flatten_and_move(src, dest)

    assert (dest / "keep.txt").read_text(encoding="utf-8") == "new"
    assert (dest / "subdir" / "inner.txt").read_text(encoding="utf-8") == "new-inner"
    assert not (dest / "subdir" / "stale.txt").exists()


# ---------------------------------------------------------------------------
# _find_nexus_archive
# ---------------------------------------------------------------------------


def test_find_nexus_archive_no_dir(tmp_path):
    assert tm._find_nexus_archive(tmp_path / "missing", 123) is None


def test_find_nexus_archive_no_match(tmp_path):
    (tmp_path / "SomeOtherMod-999-1-0.zip").write_bytes(b"")
    assert tm._find_nexus_archive(tmp_path, 5447) is None


def test_find_nexus_archive_picks_latest(tmp_path):
    old = tmp_path / "ConfigApp-5447-1-0.zip"
    new = tmp_path / "ConfigApp-5447-1-1.zip"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    import os
    import time

    old_time = time.time() - 100
    os.utime(old, (old_time, old_time))

    found = tm._find_nexus_archive(tmp_path, 5447)
    assert found == new


def test_find_nexus_archive_ignores_unsupported_ext(tmp_path):
    (tmp_path / "ConfigApp-5447-1-0.txt").write_bytes(b"")
    assert tm._find_nexus_archive(tmp_path, 5447) is None


# ---------------------------------------------------------------------------
# _install_nexus_tool
# ---------------------------------------------------------------------------


def test_install_nexus_tool_no_archive_not_installed(tmp_path):
    entry = tm.ToolEntry(
        name="ConfigApp",
        local_dir="Tools/ConfigApp",
        github_owner=None,
        github_repo=None,
        nexus_mod_id=5447,
    )
    dest_dir = tmp_path / "Tools" / "ConfigApp"
    logs = []
    tm._install_nexus_tool(entry, tmp_path, dest_dir, log=logs.append)
    assert any("pas de compte Nexus Premium" in m for m in logs)


def test_install_nexus_tool_no_archive_already_installed(tmp_path):
    entry = tm.ToolEntry(
        name="ConfigApp",
        local_dir="Tools/ConfigApp",
        github_owner=None,
        github_repo=None,
        nexus_mod_id=5447,
    )
    dest_dir = tmp_path / "Tools" / "ConfigApp"
    dest_dir.mkdir(parents=True)
    (dest_dir / tm.VERSION_MARKER_NAME).write_text("archive.zip", encoding="utf-8")
    logs = []
    tm._install_nexus_tool(entry, tmp_path, dest_dir, log=logs.append)
    assert any("déjà installé" in m for m in logs)


def test_install_nexus_tool_already_up_to_date_removes_duplicate_archive(tmp_path):
    entry = tm.ToolEntry(
        name="ConfigApp",
        local_dir="Tools/ConfigApp",
        github_owner=None,
        github_repo=None,
        nexus_mod_id=5447,
    )
    tools_root = tmp_path / "Tools"
    tools_root.mkdir()
    archive = tools_root / "ConfigApp-5447-1-0.zip"
    archive.write_bytes(b"data")
    dest_dir = tools_root / "ConfigApp"
    dest_dir.mkdir()
    (dest_dir / tm.VERSION_MARKER_NAME).write_text(archive.name, encoding="utf-8")

    logs = []
    tm._install_nexus_tool(entry, tmp_path, dest_dir, log=logs.append)
    assert any("déjà à jour" in m for m in logs)
    assert not archive.exists()


def test_install_nexus_tool_installs_new_archive(tmp_path):
    entry = tm.ToolEntry(
        name="ConfigApp",
        local_dir="Tools/ConfigApp",
        github_owner=None,
        github_repo=None,
        nexus_mod_id=5447,
    )
    tools_root = tmp_path / "Tools"
    tools_root.mkdir()
    archive = tools_root / "ConfigApp-5447-1-1.zip"
    archive.write_bytes(b"data")
    dest_dir = tools_root / "ConfigApp"

    def fake_extract(archive_path, extract_dir):
        extract_dir.mkdir(parents=True)
        (extract_dir / "app.exe").write_bytes(b"exe")

    logs = []
    with patch.object(tm, "extract_archive", side_effect=fake_extract):
        tm._install_nexus_tool(entry, tmp_path, dest_dir, log=logs.append)

    assert (dest_dir / "app.exe").exists()
    assert (dest_dir / tm.VERSION_MARKER_NAME).read_text(encoding="utf-8") == archive.name
    installed_archive = tools_root / tm.NEXUS_TOOL_ARCHIVE_SUBDIR / archive.name
    assert installed_archive.exists()
    assert not archive.exists()
    assert any("installé dans" in m for m in logs)


def test_install_nexus_tool_extract_failure_logs_and_returns(tmp_path):
    entry = tm.ToolEntry(
        name="ConfigApp",
        local_dir="Tools/ConfigApp",
        github_owner=None,
        github_repo=None,
        nexus_mod_id=5447,
    )
    tools_root = tmp_path / "Tools"
    tools_root.mkdir()
    archive = tools_root / "ConfigApp-5447-1-1.zip"
    archive.write_bytes(b"data")
    dest_dir = tools_root / "ConfigApp"

    logs = []
    with patch.object(tm, "extract_archive", side_effect=tm.ArchiveError("bad zip")):
        tm._install_nexus_tool(entry, tmp_path, dest_dir, log=logs.append)

    assert any("échec d'extraction" in m for m in logs)
    # L'archive n'a pas été déplacée puisque l'extraction a échoué.
    assert archive.exists()


# ---------------------------------------------------------------------------
# _add_local_exclude
# ---------------------------------------------------------------------------


def test_add_local_exclude_not_a_git_repo(tmp_path):
    with patch.object(tm, "_run_git", return_value=_cp(returncode=1)):
        tm._add_local_exclude(tmp_path, "/dist/")
    # Aucun fichier créé.
    assert not (tmp_path / ".git").exists()


def test_add_local_exclude_creates_and_appends(tmp_path):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    with patch.object(tm, "_run_git", return_value=_cp(stdout=".git\n")):
        tm._add_local_exclude(tmp_path, "/dist/", "/marker")
    exclude = git_dir / "info" / "exclude"
    content = exclude.read_text(encoding="utf-8")
    assert "/dist/" in content
    assert "/marker" in content


def test_add_local_exclude_idempotent(tmp_path):
    git_dir = tmp_path / ".git"
    (git_dir / "info").mkdir(parents=True)
    exclude = git_dir / "info" / "exclude"
    exclude.write_text("/dist/\n", encoding="utf-8")
    with patch.object(tm, "_run_git", return_value=_cp(stdout=".git\n")):
        tm._add_local_exclude(tmp_path, "/dist/")
    content = exclude.read_text(encoding="utf-8")
    assert content.count("/dist/") == 1


def test_add_local_exclude_absolute_git_dir(tmp_path):
    real_git_dir = tmp_path / "real-git-dir"
    real_git_dir.mkdir()
    with patch.object(tm, "_run_git", return_value=_cp(stdout=f"{real_git_dir}\n")):
        tm._add_local_exclude(tmp_path, "/dist/")
    assert (real_git_dir / "info" / "exclude").read_text(encoding="utf-8").strip() == "/dist/"


# ---------------------------------------------------------------------------
# _release_subdir_name
# ---------------------------------------------------------------------------


def test_release_subdir_name_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text("", encoding="utf-8")
    assert tm._release_subdir_name(tmp_path) == "release"


def test_release_subdir_name_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    assert tm._release_subdir_name(tmp_path) == "dist"


def test_release_subdir_name_default(tmp_path):
    assert tm._release_subdir_name(tmp_path) == "dist"


# ---------------------------------------------------------------------------
# _github_release
# ---------------------------------------------------------------------------


def _fake_httpx_client(responses):
    """`responses` : liste de MagicMock retournés successivement par
    `client.get`."""
    client = MagicMock()
    client.get.side_effect = responses
    ctx = MagicMock()
    ctx.__enter__.return_value = client
    ctx.__exit__.return_value = False
    return ctx


def _resp(status_code=200, json_data=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data or {}
    return r


def test_github_release_asset_zip():
    latest = _resp(
        200,
        {
            "tag_name": "v1.0",
            "assets": [{"name": "tool.zip", "browser_download_url": "http://x/tool.zip"}],
        },
    )
    with patch.object(tm.httpx, "Client", return_value=_fake_httpx_client([latest])):
        release = tm._github_release("Owner", "Repo")
    assert release.asset_name == "tool.zip"
    assert release.version == "v1.0"


def test_github_release_fallback_zipball():
    latest = _resp(200, {"tag_name": "v2.0", "assets": [], "zipball_url": "http://x/zip"})
    with patch.object(tm.httpx, "Client", return_value=_fake_httpx_client([latest])):
        release = tm._github_release("Owner", "Repo")
    assert release.download_url == "http://x/zip"
    assert release.asset_name == "Repo-v2.0.zip"


def test_github_release_no_release_but_repo_exists():
    latest = _resp(404)
    repo = _resp(200)
    with patch.object(tm.httpx, "Client", return_value=_fake_httpx_client([latest, repo])):
        release = tm._github_release("Owner", "Repo")
    assert release is None


def test_github_release_repo_not_found():
    latest = _resp(404)
    repo = _resp(404)
    with patch.object(tm.httpx, "Client", return_value=_fake_httpx_client([latest, repo])):
        with pytest.raises(tm.ToolsError, match="Dépôt GitHub introuvable"):
            tm._github_release("Owner", "Repo")


def test_github_release_no_zip_asset_no_zipball():
    latest = _resp(
        200, {"tag_name": "v1.0", "assets": [{"name": "readme.md", "browser_download_url": "x"}]}
    )
    with patch.object(tm.httpx, "Client", return_value=_fake_httpx_client([latest])):
        release = tm._github_release("Owner", "Repo")
    assert release is None


# ---------------------------------------------------------------------------
# _install_github_release
# ---------------------------------------------------------------------------


def test_install_github_release_already_up_to_date(tmp_path):
    dest_dir = tmp_path / "Tools" / "Repo"
    dist_dir = dest_dir / "dist"
    dist_dir.mkdir(parents=True)
    (dist_dir / tm.VERSION_MARKER_NAME).write_text("v1.0", encoding="utf-8")
    release = tm.ToolRelease(asset_name="tool.zip", download_url="http://x", version="v1.0")

    logs = []
    tm._install_github_release(
        tm.ToolEntry("Repo", "Tools/Repo", "Owner", "Repo"), dest_dir, release, log=logs.append
    )
    assert any("déjà à jour" in m for m in logs)


def test_install_github_release_downloads_and_extracts(tmp_path):
    dest_dir = tmp_path / "Tools" / "Repo"
    dest_dir.mkdir(parents=True)
    release = tm.ToolRelease(
        asset_name="tool.zip", download_url="http://x/tool.zip", version="v1.0"
    )

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.iter_bytes.return_value = [b"chunk1", b"chunk2"]
    stream_ctx = MagicMock()
    stream_ctx.__enter__.return_value = fake_resp
    stream_ctx.__exit__.return_value = False

    def fake_extract(archive_path, extract_dir):
        extract_dir.mkdir(parents=True)
        (extract_dir / "bin.exe").write_bytes(b"exe")

    logs = []
    with (
        patch.object(tm.httpx, "stream", return_value=stream_ctx),
        patch.object(tm, "extract_archive", side_effect=fake_extract),
        patch.object(tm, "_add_local_exclude") as add_exclude,
    ):
        tm._install_github_release(
            tm.ToolEntry("Repo", "Tools/Repo", "Owner", "Repo"), dest_dir, release, log=logs.append
        )

    assert (dest_dir / "dist" / "bin.exe").exists()
    assert (dest_dir / "dist" / tm.VERSION_MARKER_NAME).read_text(encoding="utf-8") == "v1.0"
    add_exclude.assert_called_once()
    assert any("installée dans" in m for m in logs)


def test_install_github_release_download_http_error(tmp_path):
    import httpx

    dest_dir = tmp_path / "Tools" / "Repo"
    dest_dir.mkdir(parents=True)
    release = tm.ToolRelease(
        asset_name="tool.zip", download_url="http://x/tool.zip", version="v1.0"
    )

    logs = []
    with patch.object(tm.httpx, "stream", side_effect=httpx.HTTPError("network down")):
        tm._install_github_release(
            tm.ToolEntry("Repo", "Tools/Repo", "Owner", "Repo"), dest_dir, release, log=logs.append
        )
    assert any("échec du téléchargement" in m for m in logs)


def test_install_github_release_extract_failure(tmp_path):
    dest_dir = tmp_path / "Tools" / "Repo"
    dest_dir.mkdir(parents=True)
    release = tm.ToolRelease(
        asset_name="tool.zip", download_url="http://x/tool.zip", version="v1.0"
    )

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.iter_bytes.return_value = [b"chunk"]
    stream_ctx = MagicMock()
    stream_ctx.__enter__.return_value = fake_resp
    stream_ctx.__exit__.return_value = False

    logs = []
    with (
        patch.object(tm.httpx, "stream", return_value=stream_ctx),
        patch.object(tm, "extract_archive", side_effect=tm.ArchiveError("corrupt")),
    ):
        tm._install_github_release(
            tm.ToolEntry("Repo", "Tools/Repo", "Owner", "Repo"), dest_dir, release, log=logs.append
        )
    assert any("échec d'extraction de la release" in m for m in logs)


# ---------------------------------------------------------------------------
# download_and_extract_tool
# ---------------------------------------------------------------------------


def test_download_and_extract_tool_no_local_dir(tmp_path):
    entry = tm.ToolEntry(name="Manual", local_dir=None, github_owner=None, github_repo=None)
    logs = []
    tm.download_and_extract_tool(entry, tmp_path, log=logs.append)
    assert any("pas de dossier local défini" in m for m in logs)


def test_download_and_extract_tool_nexus(tmp_path):
    entry = tm.ToolEntry(
        name="ConfigApp",
        local_dir="Tools/ConfigApp",
        github_owner=None,
        github_repo=None,
        nexus_mod_id=5447,
    )
    with patch.object(tm, "_install_nexus_tool") as install_nexus:
        tm.download_and_extract_tool(entry, tmp_path)
    install_nexus.assert_called_once()


def test_download_and_extract_tool_no_github_no_nexus(tmp_path):
    entry = tm.ToolEntry(
        name="Manual", local_dir="Tools/Manual", github_owner=None, github_repo=None
    )
    logs = []
    tm.download_and_extract_tool(entry, tmp_path, log=logs.append)
    assert any("installation manuelle requise" in m for m in logs)


def test_download_and_extract_tool_submodule_error(tmp_path):
    entry = tm.ToolEntry(
        name="Repo", local_dir="Tools/Repo", github_owner="Owner", github_repo="Repo"
    )
    logs = []
    with patch.object(tm, "_add_or_update_git_submodule", side_effect=tm.ToolsError("git broken")):
        tm.download_and_extract_tool(entry, tmp_path, log=logs.append)
    assert any("git broken" in m for m in logs)


def test_download_and_extract_tool_full_flow_no_release(tmp_path):
    entry = tm.ToolEntry(
        name="Repo", local_dir="Tools/Repo", github_owner="Owner", github_repo="Repo"
    )
    (tmp_path / "Tools" / "Repo").mkdir(parents=True)
    logs = []
    with (
        patch.object(tm, "_add_or_update_git_submodule", return_value="abc1234"),
        patch.object(tm, "_add_local_exclude"),
        patch.object(tm, "_github_release", return_value=None),
    ):
        tm.download_and_extract_tool(entry, tmp_path, log=logs.append)
    dest_dir = tmp_path / "Tools" / "Repo"
    assert (dest_dir / tm.VERSION_MARKER_NAME).read_text(encoding="utf-8") == "abc1234"
    assert any("source clonée dans" in m for m in logs)


def test_download_and_extract_tool_already_up_to_date(tmp_path):
    entry = tm.ToolEntry(
        name="Repo", local_dir="Tools/Repo", github_owner="Owner", github_repo="Repo"
    )
    dest_dir = tmp_path / "Tools" / "Repo"
    dest_dir.mkdir(parents=True)
    (dest_dir / tm.VERSION_MARKER_NAME).write_text("abc1234", encoding="utf-8")

    logs = []
    with (
        patch.object(tm, "_add_or_update_git_submodule", return_value="abc1234"),
        patch.object(tm, "_github_release", return_value=None),
    ):
        tm.download_and_extract_tool(entry, tmp_path, log=logs.append)
    assert any("source déjà à jour" in m for m in logs)


def test_download_and_extract_tool_release_lookup_error(tmp_path):
    entry = tm.ToolEntry(
        name="Repo", local_dir="Tools/Repo", github_owner="Owner", github_repo="Repo"
    )
    (tmp_path / "Tools" / "Repo").mkdir(parents=True)
    logs = []
    with (
        patch.object(tm, "_add_or_update_git_submodule", return_value="abc1234"),
        patch.object(tm, "_add_local_exclude"),
        patch.object(tm, "_github_release", side_effect=tm.ToolsError("dépôt introuvable")),
    ):
        tm.download_and_extract_tool(entry, tmp_path, log=logs.append)
    assert any("dépôt introuvable" in m for m in logs)


def test_download_and_extract_tool_with_release(tmp_path):
    entry = tm.ToolEntry(
        name="Repo", local_dir="Tools/Repo", github_owner="Owner", github_repo="Repo"
    )
    (tmp_path / "Tools" / "Repo").mkdir(parents=True)
    release = tm.ToolRelease(asset_name="tool.zip", download_url="http://x", version="v1.0")
    with (
        patch.object(tm, "_add_or_update_git_submodule", return_value="abc1234"),
        patch.object(tm, "_add_local_exclude"),
        patch.object(tm, "_github_release", return_value=release),
        patch.object(tm, "_install_github_release") as install_release,
    ):
        tm.download_and_extract_tool(entry, tmp_path)
    install_release.assert_called_once()


# ---------------------------------------------------------------------------
# find_executables
# ---------------------------------------------------------------------------


def test_find_executables_missing_dir(tmp_path):
    assert tm.find_executables(tmp_path / "missing") == []


def test_find_executables_finds_exe_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    a = tmp_path / "a.exe"
    b = tmp_path / "sub" / "b.exe"
    a.write_bytes(b"")
    b.write_bytes(b"")
    (tmp_path / "c.txt").write_bytes(b"")

    found = tm.find_executables(tmp_path)
    assert found == sorted([a, b])
