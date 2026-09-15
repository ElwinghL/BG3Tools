"""Tests complémentaires pour bg3_mod_tui/pak_metadata.py — couvre
_run_divine, parse_meta_lsx(_dependencies), le repli Divine.exe complet de
read_pak_identity/read_pak_module_metadata, et les fonctions d'index
(build_module_metadata_index, build_deployed_uuid_index,
archive_pak_identities). Voir tests/test_pak_metadata.py pour les tests
existants sur le choix natif/repli. Divine.exe (subprocess) et les
extractions d'archive sont mockés."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bg3_mod_tui import pak_metadata as pm
from bg3_mod_tui.pak_reader import PakReaderError


# ---------------------------------------------------------------------------
# parse_meta_lsx
# ---------------------------------------------------------------------------


def _write_meta_lsx(path: Path, *, uuid="abc-123", name="MyMod", include_module_info=True):
    if include_module_info:
        attrs = f'<attribute id="UUID" value="{uuid}"/>' if uuid else ""
        if name:
            attrs += f'<attribute id="Name" value="{name}"/>'
        body = f'<node id="ModuleInfo">{attrs}</node>'
    else:
        body = '<node id="Other"/>'
    path.write_text(
        f'<save><region id="Config"><node id="root">{body}</node></region></save>', encoding="utf-8"
    )


def test_parse_meta_lsx_valid(tmp_path):
    meta = tmp_path / "meta.lsx"
    _write_meta_lsx(meta)
    assert pm.parse_meta_lsx(meta) == ("abc-123", "MyMod")


def test_parse_meta_lsx_missing_name_defaults_empty(tmp_path):
    meta = tmp_path / "meta.lsx"
    _write_meta_lsx(meta, name=None)
    assert pm.parse_meta_lsx(meta) == ("abc-123", "")


def test_parse_meta_lsx_no_module_info(tmp_path):
    meta = tmp_path / "meta.lsx"
    _write_meta_lsx(meta, include_module_info=False)
    assert pm.parse_meta_lsx(meta) is None


def test_parse_meta_lsx_no_uuid(tmp_path):
    meta = tmp_path / "meta.lsx"
    _write_meta_lsx(meta, uuid=None, name="X")
    assert pm.parse_meta_lsx(meta) is None


def test_parse_meta_lsx_invalid_xml(tmp_path):
    meta = tmp_path / "meta.lsx"
    meta.write_text("not xml <<<", encoding="utf-8")
    assert pm.parse_meta_lsx(meta) is None


def test_parse_meta_lsx_missing_file(tmp_path):
    assert pm.parse_meta_lsx(tmp_path / "missing.lsx") is None


# ---------------------------------------------------------------------------
# parse_meta_lsx_dependencies
# ---------------------------------------------------------------------------


def test_parse_meta_lsx_dependencies_missing_file(tmp_path):
    assert pm.parse_meta_lsx_dependencies(tmp_path / "missing.lsx") == []


def test_parse_meta_lsx_dependencies_delegates_to_bytes_parser(tmp_path):
    meta = tmp_path / "meta.lsx"
    meta.write_bytes(b"<save/>")
    with patch.object(
        pm, "parse_meta_lsx_dependencies_bytes", return_value=[("dep-uuid", "DepName")]
    ) as parser:
        result = pm.parse_meta_lsx_dependencies(meta)
    assert result == [("dep-uuid", "DepName")]
    parser.assert_called_once_with(b"<save/>")


# ---------------------------------------------------------------------------
# _run_divine
# ---------------------------------------------------------------------------


def test_run_divine_windows_success(monkeypatch):
    monkeypatch.setattr(pm, "is_windows", lambda: True)
    with patch.object(
        pm.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
    ) as run:
        pm._run_divine(Path("Divine.exe"), ["-a", "x"], reference_path=Path("/tmp"))
    args, kwargs = run.call_args
    assert args[0] == ["Divine.exe", "-a", "x"]
    assert kwargs["env"] is None


def test_run_divine_linux_no_proton_prefix_raises(monkeypatch):
    monkeypatch.setattr(pm, "is_windows", lambda: False)
    monkeypatch.setattr(pm, "find_proton_prefix", lambda _ref: None)
    with pytest.raises(pm.PakMetadataError, match="préfixe Proton"):
        pm._run_divine(Path("Divine.exe"), [], reference_path=Path("/tmp"))


def test_run_divine_linux_success_sets_wineprefix(monkeypatch):
    monkeypatch.setattr(pm, "is_windows", lambda: False)
    monkeypatch.setattr(pm, "find_proton_prefix", lambda _ref: Path("/fake/prefix"))
    monkeypatch.setattr(pm, "resolve_wine_bin", lambda _prefix: "/usr/bin/wine")
    captured = {}

    def fake_run(command, env=None, **kwargs):
        captured["command"] = command
        captured["env"] = env
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pm.subprocess, "run", fake_run)
    pm._run_divine(Path("/tools/Divine.exe"), ["-a", "x"], reference_path=Path("/tmp"))
    assert captured["command"][0] == "/usr/bin/wine"
    assert captured["env"]["WINEPREFIX"] == str(Path("/fake/prefix"))


def test_run_divine_timeout_raises(monkeypatch):
    monkeypatch.setattr(pm, "is_windows", lambda: True)

    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="Divine.exe", timeout=1)

    monkeypatch.setattr(pm.subprocess, "run", raise_timeout)
    with pytest.raises(pm.PakMetadataError, match="Timeout"):
        pm._run_divine(Path("Divine.exe"), [], reference_path=Path("/tmp"))


def test_run_divine_oserror_raises(monkeypatch):
    monkeypatch.setattr(pm, "is_windows", lambda: True)

    def raise_oserror(*a, **kw):
        raise OSError("boom")

    monkeypatch.setattr(pm.subprocess, "run", raise_oserror)
    with pytest.raises(pm.PakMetadataError, match="Échec du lancement"):
        pm._run_divine(Path("Divine.exe"), [], reference_path=Path("/tmp"))


def test_run_divine_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(pm, "is_windows", lambda: True)
    monkeypatch.setattr(
        pm.subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="échec"
        ),
    )
    with pytest.raises(pm.PakMetadataError, match="échec"):
        pm._run_divine(Path("Divine.exe"), [], reference_path=Path("/tmp"))


# ---------------------------------------------------------------------------
# read_pak_identity : repli Divine.exe complet
# ---------------------------------------------------------------------------


def test_read_pak_identity_divine_fallback_no_meta_found(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pm, "_read_pak_identity_native", lambda _p: (_ for _ in ()).throw(PakReaderError("bad"))
    )
    monkeypatch.setattr(pm, "_run_divine", lambda *a, **kw: None)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_identity(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result is None


def test_read_pak_identity_divine_fallback_finds_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pm, "_read_pak_identity_native", lambda _p: (_ for _ in ()).throw(PakReaderError("bad"))
    )

    def fake_run_divine(divine_exe, args, *, reference_path, timeout=None):
        work_dir = Path(args[args.index("-d") + 1])
        (work_dir / "meta.lsx").write_text("", encoding="utf-8")

    monkeypatch.setattr(pm, "_run_divine", fake_run_divine)
    monkeypatch.setattr(pm, "is_windows", lambda: True)  # évite to_wine_path
    monkeypatch.setattr(pm, "parse_meta_lsx", lambda _p: ("uuid-1", "Name1"))
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_identity(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result == ("uuid-1", "Name1")


# ---------------------------------------------------------------------------
# read_pak_module_metadata : branches supplémentaires
# ---------------------------------------------------------------------------


def test_read_pak_module_metadata_no_meta_at_all_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "read_meta_lsx_or_lsf_bytes", lambda _p: None)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_module_metadata(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result is None


def test_read_pak_module_metadata_lsf_no_uuid_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "read_meta_lsx_or_lsf_bytes", lambda _p: ("lsf", b"data"))
    monkeypatch.setattr(pm, "extract_uuid_from_lsf_bytes", lambda _c: None)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_module_metadata(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result is None


def test_read_pak_module_metadata_lsf_with_uuid(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "read_meta_lsx_or_lsf_bytes", lambda _p: ("lsf", b"data"))
    monkeypatch.setattr(pm, "extract_uuid_from_lsf_bytes", lambda _c: "uuid-lsf")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_module_metadata(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result == pm.ModuleMetadata(uuid="uuid-lsf", name="", dependencies=())


def test_read_pak_module_metadata_lsx_identity_none_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "read_meta_lsx_or_lsf_bytes", lambda _p: ("lsx", b"<save/>"))
    monkeypatch.setattr(pm, "parse_meta_lsx_bytes", lambda _c: None)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_module_metadata(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result is None


def test_read_pak_module_metadata_divine_exe_none_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pm, "read_meta_lsx_or_lsf_bytes", lambda _p: (_ for _ in ()).throw(PakReaderError("bad"))
    )
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    with pytest.raises(pm.PakMetadataError, match="Divine.exe introuvable"):
        pm.read_pak_module_metadata(
            tmp_path / "mod.pak", divine_exe=None, reference_path=tmp_path, work_dir=work_dir
        )


def test_read_pak_module_metadata_divine_fallback_no_meta_found(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pm, "read_meta_lsx_or_lsf_bytes", lambda _p: (_ for _ in ()).throw(PakReaderError("bad"))
    )
    monkeypatch.setattr(pm, "_run_divine", lambda *a, **kw: None)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_module_metadata(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result is None


def test_read_pak_module_metadata_divine_fallback_identity_none(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pm, "read_meta_lsx_or_lsf_bytes", lambda _p: (_ for _ in ()).throw(PakReaderError("bad"))
    )

    def fake_run_divine(divine_exe, args, *, reference_path, timeout=None):
        work_dir = Path(args[args.index("-d") + 1])
        (work_dir / "meta.lsx").write_text("", encoding="utf-8")

    monkeypatch.setattr(pm, "_run_divine", fake_run_divine)
    monkeypatch.setattr(pm, "is_windows", lambda: True)
    monkeypatch.setattr(pm, "parse_meta_lsx", lambda _p: None)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_module_metadata(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result is None


def test_read_pak_module_metadata_divine_fallback_full_success(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pm, "read_meta_lsx_or_lsf_bytes", lambda _p: (_ for _ in ()).throw(PakReaderError("bad"))
    )

    def fake_run_divine(divine_exe, args, *, reference_path, timeout=None):
        work_dir = Path(args[args.index("-d") + 1])
        (work_dir / "meta.lsx").write_text("", encoding="utf-8")

    monkeypatch.setattr(pm, "_run_divine", fake_run_divine)
    monkeypatch.setattr(pm, "is_windows", lambda: True)
    monkeypatch.setattr(pm, "parse_meta_lsx", lambda _p: ("uuid-2", "Name2"))
    monkeypatch.setattr(pm, "parse_meta_lsx_dependencies", lambda _p: [("dep", "Dep")])
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pm.read_pak_module_metadata(
        tmp_path / "mod.pak",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result == pm.ModuleMetadata(uuid="uuid-2", name="Name2", dependencies=(("dep", "Dep"),))


# ---------------------------------------------------------------------------
# build_module_metadata_index / build_deployed_uuid_index
# ---------------------------------------------------------------------------


def test_build_module_metadata_index_mixes_success_and_failure(tmp_path, monkeypatch):
    pak_ok = tmp_path / "ok.pak"
    pak_fail = tmp_path / "fail.pak"
    pak_ok.write_bytes(b"")
    pak_fail.write_bytes(b"")

    def fake_read(pak, *, divine_exe, reference_path, work_dir):
        if pak == pak_ok:
            return pm.ModuleMetadata(uuid="u1", name="", dependencies=())
        raise pm.PakMetadataError("échec lecture")

    monkeypatch.setattr(pm, "read_pak_module_metadata", fake_read)
    logs = []
    index = pm.build_module_metadata_index(
        [pak_ok, pak_fail], divine_exe=None, reference_path=tmp_path, log=logs.append
    )
    assert set(index) == {"u1"}
    assert index["u1"].name == "ok"  # nom vide -> repli sur pak.stem
    assert any("échec lecture" in m for m in logs)


def test_build_deployed_uuid_index_mixes_success_and_failure(tmp_path, monkeypatch):
    pak_ok = tmp_path / "ok.pak"
    pak_fail = tmp_path / "fail.pak"
    pak_ok.write_bytes(b"")
    pak_fail.write_bytes(b"")

    def fake_read(pak, *, divine_exe, reference_path, work_dir):
        if pak == pak_ok:
            return ("u1", "")
        raise pm.PakMetadataError("échec")

    monkeypatch.setattr(pm, "read_pak_identity", fake_read)
    logs = []
    index = pm.build_deployed_uuid_index(
        [pak_ok, pak_fail], divine_exe=Path("Divine.exe"), reference_path=tmp_path, log=logs.append
    )
    assert index == {"u1": "ok"}
    assert any("échec" in m for m in logs)


def test_build_deployed_uuid_index_many_paks_uses_step_interval(tmp_path, monkeypatch):
    paks = []
    for i in range(25):
        p = tmp_path / f"mod{i}.pak"
        p.write_bytes(b"")
        paks.append(p)
    monkeypatch.setattr(pm, "read_pak_identity", lambda *a, **kw: None)
    logs = []
    pm.build_deployed_uuid_index(
        paks, divine_exe=Path("Divine.exe"), reference_path=tmp_path, log=logs.append
    )
    # step=10 pour plus de 20 paks : moins d'une ligne de log par .pak.
    assert len(logs) < 25


# ---------------------------------------------------------------------------
# archive_pak_identities
# ---------------------------------------------------------------------------


def test_archive_pak_identities_extract_error(tmp_path, monkeypatch):
    from bg3_mod_tui.archives import ArchiveError

    monkeypatch.setattr(
        pm, "extract_archive", lambda *a, **kw: (_ for _ in ()).throw(ArchiveError("bad archive"))
    )
    logs = []
    result = pm.archive_pak_identities(
        tmp_path / "mod.zip",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        log=logs.append,
    )
    assert result == []
    assert any("bad archive" in m for m in logs)


def test_archive_pak_identities_no_pak_found(tmp_path, monkeypatch):
    monkeypatch.setattr(
        pm, "extract_archive", lambda archive, dest: dest.mkdir(parents=True, exist_ok=True)
    )
    result = pm.archive_pak_identities(
        tmp_path / "mod.zip", divine_exe=Path("Divine.exe"), reference_path=tmp_path
    )
    assert result == []


def test_archive_pak_identities_success_and_failure_mixed(tmp_path, monkeypatch):
    def fake_extract(archive, dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "a.pak").write_bytes(b"")
        (dest / "b.pak").write_bytes(b"")

    monkeypatch.setattr(pm, "extract_archive", fake_extract)

    def fake_read(pak, *, divine_exe, reference_path, work_dir):
        if pak.name == "a.pak":
            return ("uuid-a", "NameA")
        raise pm.PakMetadataError("échec b")

    monkeypatch.setattr(pm, "read_pak_identity", fake_read)
    logs = []
    result = pm.archive_pak_identities(
        tmp_path / "mod.zip",
        divine_exe=Path("Divine.exe"),
        reference_path=tmp_path,
        log=logs.append,
    )
    assert result == [("uuid-a", "NameA")]
    assert any("échec b" in m for m in logs)
