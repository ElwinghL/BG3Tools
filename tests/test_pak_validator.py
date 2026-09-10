"""Tests de `bg3_mod_tui.pak_validator` : validation structurelle d'un .pak
sur des fichiers LSPK v18 minimaux construits à la main (pas de vrai .pak
BG3 disponible dans cet environnement de test, voir `pak_reader`/
`pak_validator`) — un cas valide, et plusieurs formes de corruption
(taille déclarée incohérente, offset hors bornes, signature absente)."""

from __future__ import annotations

import struct

import lz4.block

from bg3_mod_tui.pak_validator import validate_pak, validate_paks

_SIGNATURE_BYTES = struct.pack("<I", 0x4B50534C)
_DATA_OFFSET = 40  # 4 (signature) + 36 (LSPKHeader16)


def _build_v18_pak(
    entries: list[tuple[str, bytes, int | None]], *, declared_size_on_disk: int | None = None
) -> bytes:
    """Construit un .pak LSPK v18 minimal (entrées non compressées) à
    partir d'une liste `(nom_interne, contenu, uncompressed_size_déclarée)`
    — `uncompressed_size_déclarée` à `None` signifie "= len(contenu)" (cas
    normal) ; une valeur différente sert à simuler une taille décompressée
    incohérente sans avoir à casser la décompression elle-même.

    `declared_size_on_disk`, si fourni, écrase la `SizeOnDisk` annoncée
    pour la (seule) entrée -- sert à simuler un offset+taille dépassant la
    fin réelle du fichier (entrée "hors bornes") sans toucher à la table
    des fichiers elle-même, qui reste valide et correctement positionnée."""
    offset = _DATA_OFFSET
    data_section = b""
    raw_entries = b""
    for name, content, declared_uncompressed in entries:
        name_bytes = name.encode("utf-8").ljust(256, b"\0")
        uncompressed_size = declared_uncompressed if declared_uncompressed is not None else len(content)
        size_on_disk = declared_size_on_disk if declared_size_on_disk is not None else len(content)
        raw_entries += struct.pack(
            "<256sIHBBII",
            name_bytes,
            offset,  # OffsetInFile1
            0,  # OffsetInFile2
            0,  # ArchivePart
            0,  # Flags (méthode de compression = 0 = aucune)
            size_on_disk,  # SizeOnDisk (potentiellement mensongère, voir ci-dessus)
            uncompressed_size,  # UncompressedSize
        )
        data_section += content
        offset += len(content)

    file_list_offset = _DATA_OFFSET + len(data_section)
    compressed_entries = lz4.block.compress(raw_entries, store_size=False)

    header = struct.pack(
        "<IQIBB16sH",
        18,  # Version
        file_list_offset,
        len(compressed_entries),
        0,  # Flags
        0,  # Priority
        b"\0" * 16,  # Md5
        len(entries),  # NumParts (peu importe ici, non utilisé par PakArchive)
    )
    file_list_section = struct.pack("<II", len(entries), len(compressed_entries)) + compressed_entries

    return _SIGNATURE_BYTES + header + data_section + file_list_section


_META_LSX = b"<save><region id='Config'/></save>"


def test_validate_pak_valide(tmp_path):
    pak_path = tmp_path / "MonMod.pak"
    pak_path.write_bytes(_build_v18_pak([("Mods/MonMod/meta.lsx", _META_LSX, None)]))

    result = validate_pak(pak_path)
    assert result.valid is True
    assert result.errors == []
    assert result.num_entries == 1
    assert result.checked_entries == 1


def test_validate_pak_taille_declaree_incoherente(tmp_path):
    pak_path = tmp_path / "TailleIncoherente.pak"
    # Déclare une UncompressedSize différente de la taille réelle du
    # contenu stocké : la décompression (triviale, méthode = aucune)
    # réussit techniquement, mais la taille obtenue ne correspond pas à ce
    # que la table des fichiers annonçait -> détecté comme incohérence.
    pak_path.write_bytes(
        _build_v18_pak([("Mods/MonMod/meta.lsx", _META_LSX, len(_META_LSX) + 100)])
    )

    result = validate_pak(pak_path)
    assert result.valid is False
    assert result.num_entries == 1
    assert result.checked_entries == 1
    assert len(result.errors) == 1
    assert "incohérente" in result.errors[0]


def test_validate_pak_offset_hors_bornes(tmp_path):
    # Déclare une SizeOnDisk plus grande que le contenu réellement stocké
    # dans le .pak : la table des fichiers elle-même reste valide et
    # correctement positionnée (contrairement à une simple troncature du
    # fichier), mais `entry.offset + entry.size_on_disk` dépasse la fin
    # réelle du fichier mappé -> CorruptedPak levée par `PakArchive.read`.
    pak_path = tmp_path / "OffsetHorsBornes.pak"
    pak_path.write_bytes(
        _build_v18_pak(
            [("Mods/MonMod/meta.lsx", _META_LSX, None)],
            declared_size_on_disk=len(_META_LSX) + 10_000,
        )
    )

    result = validate_pak(pak_path)
    assert result.valid is False
    # L'ouverture (header + table des fichiers) réussit : l'incohérence
    # n'est détectée qu'à la lecture de l'entrée elle-même.
    assert result.num_entries == 1
    assert result.checked_entries == 1
    assert len(result.errors) == 1
    assert "MonMod/meta.lsx" in result.errors[0]


def test_validate_pak_signature_absente(tmp_path):
    pak_path = tmp_path / "PasUnPak.pak"
    pak_path.write_bytes(b"PK\x03\x04" + b"\0" * 100)  # en-tête zip, pas LSPK

    result = validate_pak(pak_path)
    assert result.valid is False
    assert result.num_entries == 0
    assert result.checked_entries == 0
    assert len(result.errors) == 1


def test_validate_paks_rapport_structure(tmp_path):
    valid_path = tmp_path / "Valide.pak"
    valid_path.write_bytes(_build_v18_pak([("Mods/Valide/meta.lsx", _META_LSX, None)]))

    invalid_path = tmp_path / "Invalide.pak"
    invalid_path.write_bytes(
        _build_v18_pak([("Mods/Invalide/meta.lsx", _META_LSX, len(_META_LSX) + 1)])
    )

    report = validate_paks([valid_path, invalid_path])

    assert {r.path for r in report["valid"]} == {valid_path}
    assert {r.path for r in report["invalid"]} == {invalid_path}
    assert report["invalid"][0].errors
