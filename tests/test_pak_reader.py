"""Tests de `bg3_mod_tui.pak_reader` : parsing du header LSPK (v16/v18),
détection des formats non gérés (déclenche le repli Divine.exe côté
appelant, voir `pak_metadata.py`), lecture d'une entrée via `PakArchive`
sur un .pak minimal construit à la main (pas de vrai .pak BG3 disponible
dans cet environnement de test), extraction `meta.lsx` (XML) et extraction
d'UUID par regex sur `meta.lsf` (binaire)."""

from __future__ import annotations

import struct

import lz4.block
import pytest

from bg3_mod_tui.pak_reader import (
    CorruptedPak,
    PakArchive,
    UnsupportedPakVersion,
    extract_uuid_from_lsf_bytes,
    parse_file_list,
    parse_lspk_header,
    parse_meta_lsx_bytes,
    parse_meta_lsx_dependencies_bytes,
)

_SIGNATURE_BYTES = struct.pack("<I", 0x4B50534C)

_META_LSX = b"""<?xml version="1.0"?>
<save>
  <version major="4" minor="0" revision="0" build="0"/>
  <region id="Config">
    <node id="root">
      <children>
        <node id="Dependencies">
          <children>
            <node id="ModuleShortDesc">
              <attribute id="UUID" value="11111111-1111-1111-1111-111111111111" type="guid"/>
              <attribute id="Name" value="UneDependance" type="LSString"/>
            </node>
          </children>
        </node>
        <node id="ModuleInfo">
          <attribute id="UUID" value="d7cee0e7-77e4-4db8-b40d-3b30beb2eb17" type="guid"/>
          <attribute id="Name" value="Mon Mod" type="LSString"/>
          <attribute id="Folder" value="MonMod" type="LSString"/>
        </node>
      </children>
    </node>
  </region>
</save>
"""


def _build_v18_pak(entry_name: str, content: bytes) -> bytes:
    """Construit un .pak LSPK v18 minimal en mémoire, avec une seule
    entrée `entry_name` -> `content` (non compressée), pour tester
    `PakArchive` sans dépendre d'un vrai .pak BG3."""
    data_offset = 40  # 4 (signature) + 36 (LSPKHeader16)
    file_list_offset = data_offset + len(content)

    name_bytes = entry_name.encode("utf-8").ljust(256, b"\0")
    entry = struct.pack(
        "<256sIHBBII",
        name_bytes,
        data_offset,  # OffsetInFile1
        0,  # OffsetInFile2
        0,  # ArchivePart
        0,  # Flags (méthode de compression = 0 = aucune)
        len(content),  # SizeOnDisk
        len(content),  # UncompressedSize
    )
    compressed_entries = lz4.block.compress(entry, store_size=False)

    header = struct.pack(
        "<IQIBB16sH",
        18,  # Version
        file_list_offset,
        len(compressed_entries),
        0,  # Flags
        0,  # Priority
        b"\0" * 16,  # Md5
        1,  # NumParts
    )
    file_list_section = struct.pack("<II", 1, len(compressed_entries)) + compressed_entries

    return _SIGNATURE_BYTES + header + content + file_list_section


def test_parse_lspk_header_v18():
    pak_bytes = _build_v18_pak("Mods/MonMod/meta.lsx", _META_LSX)
    version, file_list_offset, file_list_size, num_parts = parse_lspk_header(pak_bytes[:40])
    assert version == 18
    assert num_parts == 1
    assert file_list_offset == 40 + len(_META_LSX)
    assert file_list_size > 0


def test_parse_lspk_header_signature_absente():
    with pytest.raises(UnsupportedPakVersion):
        parse_lspk_header(b"NOTAPAK!" + b"\0" * 40)


def test_parse_lspk_header_version_non_geree():
    header = struct.pack("<IQIBB16sH", 13, 40, 0, 0, 0, b"\0" * 16, 1)
    with pytest.raises(UnsupportedPakVersion):
        parse_lspk_header(_SIGNATURE_BYTES + header)


def test_parse_lspk_header_fichier_trop_court():
    with pytest.raises(CorruptedPak):
        parse_lspk_header(_SIGNATURE_BYTES + b"\0" * 4)


def test_parse_file_list_taille_compressee_hors_bornes():
    pak_bytes = _build_v18_pak("Mods/MonMod/meta.lsx", _META_LSX)
    _version, file_list_offset, _size, _parts = parse_lspk_header(pak_bytes[:40])
    # Corrompt la taille compressée annoncée pour qu'elle dépasse le fichier.
    corrupted = bytearray(pak_bytes)
    struct.pack_into("<I", corrupted, file_list_offset + 4, 10_000_000)
    with pytest.raises(CorruptedPak):
        parse_file_list(bytes(corrupted), 18, file_list_offset)


def test_pak_archive_find_et_read(tmp_path):
    pak_path = tmp_path / "MonMod.pak"
    pak_path.write_bytes(_build_v18_pak("Mods/MonMod/meta.lsx", _META_LSX))

    with PakArchive.open(pak_path) as pak:
        assert pak.version == 18
        entry = pak.find("Mods/MonMod/meta.lsx")
        assert entry is not None
        assert pak.read(entry) == _META_LSX

        # Insensible à la casse et trouvable par suffixe.
        assert pak.find("mods/monmod/META.LSX") is entry
        assert pak.find_suffix("meta.lsx") is entry
        assert pak.find_suffix("meta.lsf") is None
        assert pak.find("Mods/AutreMod/meta.lsx") is None


def test_pak_archive_fichier_non_lspk(tmp_path):
    pak_path = tmp_path / "PasUnPak.pak"
    pak_path.write_bytes(b"PK\x03\x04" + b"\0" * 100)  # en-tête zip, pas LSPK
    with pytest.raises(UnsupportedPakVersion):
        PakArchive.open(pak_path)


def test_parse_meta_lsx_bytes_ignore_dependencies():
    identity = parse_meta_lsx_bytes(_META_LSX)
    assert identity == ("d7cee0e7-77e4-4db8-b40d-3b30beb2eb17", "Mon Mod", "MonMod")


def test_parse_meta_lsx_bytes_xml_invalide():
    assert parse_meta_lsx_bytes(b"<pas de xml valide") is None


def test_parse_meta_lsx_bytes_sans_module_info():
    assert parse_meta_lsx_bytes(b"<save><region/></save>") is None


def test_parse_meta_lsx_dependencies_bytes_extrait_module_short_desc():
    assert parse_meta_lsx_dependencies_bytes(_META_LSX) == [
        ("11111111-1111-1111-1111-111111111111", "UneDependance")
    ]


def test_parse_meta_lsx_dependencies_bytes_sans_noeud_dependencies():
    assert parse_meta_lsx_dependencies_bytes(b"<save><region/></save>") == []


def test_parse_meta_lsx_dependencies_bytes_xml_invalide():
    assert parse_meta_lsx_dependencies_bytes(b"<pas de xml valide") == []


def test_extract_uuid_from_lsf_bytes_direct():
    data = (
        b"LSOF" + struct.pack("<I", 5) + b"...junk..."
        b"d7cee0e7-77e4-4db8-b40d-3b30beb2eb17" + b"...more junk..."
    )
    assert extract_uuid_from_lsf_bytes(data) == "d7cee0e7-77e4-4db8-b40d-3b30beb2eb17"


def test_extract_uuid_from_lsf_bytes_aucun_uuid():
    data = b"LSOF" + struct.pack("<I", 5) + b"rien d'exploitable ici"
    assert extract_uuid_from_lsf_bytes(data) is None
