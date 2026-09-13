"""Tests du repli Divine.exe de `pak_metadata.read_pak_identity` quand la
lecture native (`pak_reader`) échoue — voir `pak_metadata._read_pak_identity_native`
et son appelant. Ne teste pas Divine.exe lui-même (sous-processus Wine, hors de
portée d'un test unitaire) : `_run_divine` est simulé pour vérifier seulement
QUAND il est appelé (repli) ou non (lecture native réussie)."""

from __future__ import annotations

from pathlib import Path

import bg3_mod_tui.pak_metadata as pak_metadata
from bg3_mod_tui.pak_reader import UnsupportedPakVersion


def test_read_pak_identity_replie_sur_divine_si_lecture_native_echoue(tmp_path, monkeypatch):
    def fake_native(_pak_path):
        raise UnsupportedPakVersion("version simulée non gérée")

    calls: list[list[str]] = []

    def fake_run_divine(_divine_exe, args, *, reference_path):
        calls.append(args)

    monkeypatch.setattr(pak_metadata, "_read_pak_identity_native", fake_native)
    monkeypatch.setattr(pak_metadata, "_run_divine", fake_run_divine)

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pak_metadata.read_pak_identity(
        tmp_path / "Mod.pak",
        divine_exe=Path("/fake/Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    # Aucun meta.lsx extrait dans work_dir par le Divine.exe simulé -> None,
    # mais le point important est que le repli a bien été déclenché.
    assert result is None
    assert calls, "_run_divine doit être appelé quand la lecture native échoue."


def test_read_pak_identity_replie_sur_divine_si_exception_inattendue(tmp_path, monkeypatch):
    """Filet de sécurité (voir docstring de read_pak_identity) : même une
    exception qui n'est PAS un PakReaderError déclenche le repli, plutôt que
    de faire planter l'appelant."""

    def fake_native(_pak_path):
        raise ValueError("boom inattendu")

    calls: list[list[str]] = []

    def fake_run_divine(_divine_exe, args, *, reference_path):
        calls.append(args)

    monkeypatch.setattr(pak_metadata, "_read_pak_identity_native", fake_native)
    monkeypatch.setattr(pak_metadata, "_run_divine", fake_run_divine)

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pak_metadata.read_pak_identity(
        tmp_path / "Mod.pak",
        divine_exe=Path("/fake/Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result is None
    assert calls


def test_read_pak_identity_pas_de_repli_si_lecture_native_reussit(tmp_path, monkeypatch):
    def fake_native(_pak_path):
        return ("uuid-natif", "Nom natif")

    def fake_run_divine(*_args, **_kwargs):
        raise AssertionError("Divine.exe ne doit pas être appelé si la lecture native réussit.")

    monkeypatch.setattr(pak_metadata, "_read_pak_identity_native", fake_native)
    monkeypatch.setattr(pak_metadata, "_run_divine", fake_run_divine)

    result = pak_metadata.read_pak_identity(
        tmp_path / "Mod.pak",
        divine_exe=Path("/fake/Divine.exe"),
        reference_path=tmp_path,
        work_dir=tmp_path,
    )
    assert result == ("uuid-natif", "Nom natif")


def test_read_pak_module_metadata_replie_sur_divine_si_lecture_native_echoue(tmp_path, monkeypatch):
    """Même repli que `read_pak_identity` (voir ci-dessus), pour la variante
    qui extrait aussi les dépendances (`read_pak_module_metadata`)."""

    def fake_native(_pak_path):
        raise UnsupportedPakVersion("version simulée non gérée")

    calls: list[list[str]] = []

    def fake_run_divine(_divine_exe, args, *, reference_path):
        calls.append(args)

    monkeypatch.setattr(pak_metadata, "read_meta_lsx_or_lsf_bytes", fake_native)
    monkeypatch.setattr(pak_metadata, "_run_divine", fake_run_divine)

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    result = pak_metadata.read_pak_module_metadata(
        tmp_path / "Mod.pak",
        divine_exe=Path("/fake/Divine.exe"),
        reference_path=tmp_path,
        work_dir=work_dir,
    )
    assert result is None
    assert calls, "_run_divine doit être appelé quand la lecture native échoue."


def test_read_pak_module_metadata_pas_de_repli_si_lecture_native_reussit(tmp_path, monkeypatch):
    meta_lsx = b"""<?xml version="1.0"?>
<save><region id="Config"><node id="root"><children>
  <node id="Dependencies"><children>
    <node id="ModuleShortDesc">
      <attribute id="UUID" value="11111111-1111-1111-1111-111111111111" type="guid"/>
      <attribute id="Name" value="UneDependance" type="LSString"/>
    </node>
  </children></node>
  <node id="ModuleInfo">
    <attribute id="UUID" value="d7cee0e7-77e4-4db8-b40d-3b30beb2eb17" type="guid"/>
    <attribute id="Name" value="Mon Mod" type="LSString"/>
  </node>
</children></node></region></save>
"""

    def fake_native(_pak_path):
        return ("lsx", meta_lsx)

    def fake_run_divine(*_args, **_kwargs):
        raise AssertionError("Divine.exe ne doit pas être appelé si la lecture native réussit.")

    monkeypatch.setattr(pak_metadata, "read_meta_lsx_or_lsf_bytes", fake_native)
    monkeypatch.setattr(pak_metadata, "_run_divine", fake_run_divine)

    result = pak_metadata.read_pak_module_metadata(
        tmp_path / "Mod.pak",
        divine_exe=Path("/fake/Divine.exe"),
        reference_path=tmp_path,
        work_dir=tmp_path,
    )
    assert result.uuid == "d7cee0e7-77e4-4db8-b40d-3b30beb2eb17"
    assert result.name == "Mon Mod"
    assert result.dependencies == (("11111111-1111-1111-1111-111111111111", "UneDependance"),)
