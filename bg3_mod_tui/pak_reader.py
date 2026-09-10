"""Lecteur natif (Python pur, sans Divine.exe) du format d'archive `.pak`
de Larian ("LSPK") — sert à lire l'index d'un .pak et en extraire un
fichier interne précis (typiquement `Mods/<Dossier>/meta.lsx` ou
`meta.lsf`) sans lancer de sous-processus Wine/Divine.exe à chaque appel.

Format LSPK — documenté par le code source de référence LSLib (voir
https://github.com/Norbyte/lslib, `LSLib/LS/PackageFormat.cs` et
`PackageReader.cs`), pas de spécification officielle Larian publiée :

- Octets 0-3 : signature `b"LSPK"` (uint32 little-endian `0x4B50534C`).
- Octet 4 : version du format (uint32). BG3 Early Access = 15/16, BG3
  release = 18. Seules 16 et 18 sont gérées ici ; toute autre valeur lève
  `UnsupportedPakVersion` (charge à l'appelant de replier sur Divine.exe,
  voir `pak_metadata.py`).
- À partir de l'octet 4 : le header `LSPKHeader16` (utilisé tel quel pour
  la v16 *et* la v18 — seule la structure des entrées de fichier diffère
  entre les deux versions) :
    Version            uint32
    FileListOffset     uint64  — offset absolu de la table des fichiers
    FileListSize       uint32  — taille sur disque de la table compressée
    Flags              uint8
    Priority           uint8
    Md5                16 bytes
    NumParts           uint16
  soit 36 octets (4+8+4+1+1+16+2), en little-endian, sans padding
  (struct C# `[StructLayout(Pack = 1)]`).
- À `FileListOffset` : `NumFiles` (uint32) puis `CompressedSize` (uint32)
  puis `CompressedSize` octets de données compressées en LZ4 *bloc brut*
  (pas le format "frame" LZ4 — la taille décompressée est connue à
  l'avance : `NumFiles * sizeof(entrée de fichier)`, donc pas besoin de la
  coder dans le flux LZ4 lui-même).
- Chaque entrée de fichier encode un chemin interne (ex:
  `Mods/MonMod/meta.lsx`) sur 256 octets (chaîne C terminée par NUL),
  suivi de l'offset/taille sur disque/taille décompressée/partie
  d'archive/flags de compression :
    - v16 (`FileEntry15`, 296 octets) : Name[256], OffsetInFile u64,
      SizeOnDisk u64, UncompressedSize u64, ArchivePart u32, Flags u32,
      Crc u32, Unknown2 u32.
    - v18 (`FileEntry18`, 272 octets) : Name[256], OffsetInFile1 u32,
      OffsetInFile2 u16, ArchivePart u8, Flags u8, SizeOnDisk u32,
      UncompressedSize u32. L'offset réel 48 bits se reconstruit par
      `OffsetInFile1 | (OffsetInFile2 << 32)`.
  Le champ `Flags` (par entrée) encode la méthode de compression du
  contenu du fichier sur ses 4 bits de poids faible (0=aucune, 1=zlib,
  2=LZ4, 3=zstd — convention LSLib `CompressionFlags`/`CompressionMethod`,
  reconstituée depuis le code de référence : les 4 bits hauts encodent le
  niveau de compression, ignoré ici en lecture).

Incertitudes documentées (voir rapport de la tâche TODO correspondante) :
aucun `.pak` BG3 réel n'était disponible dans l'environnement de
développement pour valider ce parseur contre un fichier réel — en
particulier la reconstruction de l'offset 48 bits (v18) et le bitmask de
méthode de compression par entrée sont basés sur le code de référence
LSLib mais non vérifiés empiriquement. D'où l'existence du repli sur
Divine.exe (`pak_metadata.py`) dès que quoi que ce soit dans ce module
lève une exception."""

from __future__ import annotations

import mmap
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

try:
    import lz4.block as _lz4_block
except ImportError:  # pragma: no cover - dépendance normalement installée
    _lz4_block = None

try:
    import zstandard as _zstandard
except ImportError:  # pragma: no cover - dépendance normalement installée
    _zstandard = None

_SIGNATURE = 0x4B50534C  # b"LSPK" en uint32 little-endian
_SUPPORTED_VERSIONS = (16, 18)

# Header LSPKHeader16 (commun v16/v18), à partir de l'octet 4 :
# Version(I) FileListOffset(Q) FileListSize(I) Flags(B) Priority(B) Md5(16s) NumParts(H)
_HEADER_STRUCT = struct.Struct("<IQIBB16sH")

# FileEntry15 (v16) : Name(256s) OffsetInFile(Q) SizeOnDisk(Q) UncompressedSize(Q)
# ArchivePart(I) Flags(I) Crc(I) Unknown2(I)
_FILE_ENTRY_15_STRUCT = struct.Struct("<256sQQQIIII")

# FileEntry18 (v18) : Name(256s) OffsetInFile1(I) OffsetInFile2(H) ArchivePart(B)
# Flags(B) SizeOnDisk(I) UncompressedSize(I)
_FILE_ENTRY_18_STRUCT = struct.Struct("<256sIHBBII")

_COMPRESSION_METHOD_MASK = 0x0F
_COMPRESSION_NONE = 0
_COMPRESSION_ZLIB = 1
_COMPRESSION_LZ4 = 2
_COMPRESSION_ZSTD = 3


class PakReaderError(RuntimeError):
    """Erreur générique de lecture native d'un .pak — toute levée de cette
    exception (ou d'une sous-classe) doit déclencher le repli sur
    Divine.exe côté appelant (voir `pak_metadata.py`)."""


class UnsupportedPakVersion(PakReaderError):
    """Signature absente ou version LSPK non gérée par ce lecteur natif
    (autre chose que 16/18) — cas normal pour d'anciens formats DOS2 ou un
    futur format BG3 encore inconnu, pas une erreur de programmation."""


class CorruptedPak(PakReaderError):
    """Structure interne incohérente (taille de fichier trop petite,
    décompression échouée, offset hors bornes...) — .pak tronqué/corrompu,
    ou hypothèse de format erronée."""


@dataclass(frozen=True)
class PakFileEntry:
    """Une entrée de la table des fichiers d'un .pak : chemin interne
    (ex: `Mods/MonMod/meta.lsx`) et emplacement/taille de son contenu."""

    name: str
    offset: int
    size_on_disk: int
    uncompressed_size: int
    compression_method: int


def _decode_name(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace").replace("\\", "/")


def _decompress_lz4_block(data: bytes, uncompressed_size: int) -> bytes:
    if _lz4_block is None:
        raise CorruptedPak(
            "Le paquet Python 'lz4' n'est pas installé — impossible de décompresser "
            "l'index du .pak."
        )
    try:
        return _lz4_block.decompress(data, uncompressed_size=uncompressed_size)
    except Exception as exc:  # noqa: BLE001 - toute erreur lz4 -> repli Divine.exe
        raise CorruptedPak(f"Décompression LZ4 de l'index échouée : {exc}") from exc


def _decompress_entry(data: bytes, method: int, uncompressed_size: int) -> bytes:
    method &= _COMPRESSION_METHOD_MASK
    if method == _COMPRESSION_NONE:
        return data
    if method == _COMPRESSION_ZLIB:
        try:
            return zlib.decompress(data)
        except zlib.error as exc:
            raise CorruptedPak(f"Décompression zlib échouée : {exc}") from exc
    if method == _COMPRESSION_LZ4:
        return _decompress_lz4_block(data, uncompressed_size)
    if method == _COMPRESSION_ZSTD:
        if _zstandard is None:
            raise CorruptedPak(
                "Le paquet Python 'zstandard' n'est pas installé — impossible de "
                "décompresser ce fichier du .pak."
            )
        try:
            return _zstandard.ZstdDecompressor().decompress(
                data, max_output_size=uncompressed_size
            )
        except Exception as exc:  # noqa: BLE001 - toute erreur zstd -> repli Divine.exe
            raise CorruptedPak(f"Décompression zstd échouée : {exc}") from exc
    raise CorruptedPak(f"Méthode de compression inconnue (flags={method}).")


def parse_lspk_header(data: bytes) -> tuple[int, int, int, int]:
    """Parse la signature + le header `LSPKHeader16` depuis les premiers
    octets d'un .pak (`data` doit couvrir au moins les 40 premiers
    octets). Retourne `(version, file_list_offset, file_list_size,
    num_parts)`. Lève `UnsupportedPakVersion` si la signature est absente
    ou la version non gérée (16/18 seulement), `CorruptedPak` si `data`
    est trop court pour contenir le header."""
    if len(data) < 4 + _HEADER_STRUCT.size:
        raise CorruptedPak("Fichier trop court pour contenir un header LSPK.")
    (signature,) = struct.unpack_from("<I", data, 0)
    if signature != _SIGNATURE:
        raise UnsupportedPakVersion("Signature LSPK absente (pas un .pak Larian, ou format ancien).")
    version, file_list_offset, file_list_size, _flags, _priority, _md5, num_parts = (
        _HEADER_STRUCT.unpack_from(data, 4)
    )
    if version not in _SUPPORTED_VERSIONS:
        raise UnsupportedPakVersion(
            f"Version LSPK {version} non gérée par le lecteur natif (seules {_SUPPORTED_VERSIONS} "
            "le sont) — repli sur Divine.exe attendu."
        )
    return version, file_list_offset, file_list_size, num_parts


def _entry_struct_for_version(version: int) -> struct.Struct:
    return _FILE_ENTRY_18_STRUCT if version == 18 else _FILE_ENTRY_15_STRUCT


def _parse_file_entry(version: int, raw: bytes) -> PakFileEntry:
    if version == 18:
        name, offset1, offset2, _part, flags, size_on_disk, uncompressed_size = (
            _FILE_ENTRY_18_STRUCT.unpack(raw)
        )
        offset = offset1 | (offset2 << 32)
    else:
        name, offset, size_on_disk, uncompressed_size, _part, flags, _crc, _unknown2 = (
            _FILE_ENTRY_15_STRUCT.unpack(raw)
        )
    return PakFileEntry(
        name=_decode_name(name),
        offset=offset,
        size_on_disk=size_on_disk,
        uncompressed_size=uncompressed_size,
        compression_method=flags & _COMPRESSION_METHOD_MASK,
    )


def parse_file_list(data: bytes, version: int, file_list_offset: int) -> list[PakFileEntry]:
    """Parse la table des fichiers (compressée en LZ4 bloc brut) à partir
    de `file_list_offset` dans `data`. Lève `CorruptedPak` si la
    décompression échoue ou si `data` est trop court."""
    if file_list_offset + 8 > len(data):
        raise CorruptedPak("Offset de la table des fichiers hors bornes.")
    num_files, compressed_size = struct.unpack_from("<II", data, file_list_offset)
    compressed_start = file_list_offset + 8
    compressed_end = compressed_start + compressed_size
    if compressed_end > len(data):
        raise CorruptedPak("Table des fichiers tronquée (taille compressée hors bornes).")
    entry_struct = _entry_struct_for_version(version)
    uncompressed_size = num_files * entry_struct.size
    compressed = bytes(data[compressed_start:compressed_end])
    raw_entries = _decompress_lz4_block(compressed, uncompressed_size)
    if len(raw_entries) != uncompressed_size:
        raise CorruptedPak("Taille de la table des fichiers décompressée inattendue.")
    return [
        _parse_file_entry(version, raw_entries[i : i + entry_struct.size])
        for i in range(0, uncompressed_size, entry_struct.size)
    ]


class PakArchive:
    """Vue en lecture seule (mmap) sur un .pak — ouvre le fichier, parse le
    header et la table des fichiers une seule fois à la construction, puis
    permet de lire le contenu d'entrées individuelles à la demande sans
    jamais charger tout le .pak en mémoire (fichiers potentiellement de
    plusieurs Go d'assets).

    À utiliser comme context manager :

        with PakArchive.open(pak_path) as pak:
            entry = pak.find("Mods/MonMod/meta.lsx")
            if entry:
                content = pak.read(entry)

    Lève `UnsupportedPakVersion`/`CorruptedPak` (`PakReaderError`) à
    l'ouverture si le .pak n'est pas exploitable nativement — c'est le
    signal pour l'appelant de replier sur Divine.exe."""

    def __init__(self, path: Path, file_obj, mmap_obj: mmap.mmap, version: int, entries: list[PakFileEntry]):
        self._path = path
        self._file = file_obj
        self._mmap = mmap_obj
        self.version = version
        self.entries = entries
        self._by_name = {e.name.lower(): e for e in entries}

    @classmethod
    def open(cls, path: Path) -> "PakArchive":
        """Ouvre `path` en lecture seule via mmap et parse header + table
        des fichiers. Ferme proprement le fichier sous-jacent si le parsing
        échoue (pas de descripteur/mmap qui fuit sur une erreur)."""
        file_obj = open(path, "rb")
        try:
            size = path.stat().st_size
            if size == 0:
                raise CorruptedPak("Fichier .pak vide.")
            mmap_obj = mmap.mmap(file_obj.fileno(), 0, access=mmap.ACCESS_READ)
        except OSError as exc:
            file_obj.close()
            raise CorruptedPak(f"Impossible de mapper le .pak en mémoire : {exc}") from exc
        try:
            version, file_list_offset, _file_list_size, _num_parts = parse_lspk_header(
                mmap_obj[: 4 + _HEADER_STRUCT.size]
            )
            entries = parse_file_list(mmap_obj, version, file_list_offset)
        except Exception:
            mmap_obj.close()
            file_obj.close()
            raise
        return cls(path, file_obj, mmap_obj, version, entries)

    def __enter__(self) -> "PakArchive":
        return self

    def __exit__(self, *_exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._mmap.close()
        self._file.close()

    def find(self, internal_path: str) -> PakFileEntry | None:
        """Cherche une entrée par chemin interne, insensible à la casse et
        au séparateur (`\\`/`/`) — les .pak BG3 utilisent `/`, mais mieux
        vaut ne pas en dépendre absolument."""
        return self._by_name.get(internal_path.replace("\\", "/").lower())

    def find_suffix(self, suffix: str) -> PakFileEntry | None:
        """Première entrée dont le chemin interne se termine par `suffix`
        (insensible à la casse) — utile pour `meta.lsx`/`meta.lsf` dont on
        ne connaît pas le dossier de mod exact à l'avance (ex:
        `Mods/<Dossier inconnu>/meta.lsx`)."""
        suffix = suffix.replace("\\", "/").lower()
        for entry in self.entries:
            if entry.name.lower().endswith(suffix):
                return entry
        return None

    def read(self, entry: PakFileEntry) -> bytes:
        """Lit et décompresse le contenu de `entry`. Ne gère que les .pak
        en une seule partie (`ArchivePart` == 0, cas normal pour un .pak de
        mod BG3 — les .pak multi-parties sont un mécanisme des gros
        fichiers du jeu de base, pas des mods) : lève `CorruptedPak` si
        l'offset dépasse la taille du fichier mappé."""
        end = entry.offset + entry.size_on_disk
        if end > len(self._mmap):
            raise CorruptedPak(
                f"Entrée '{entry.name}' hors bornes du .pak (offset={entry.offset}, "
                f"taille mappée={len(self._mmap)})."
            )
        raw = bytes(self._mmap[entry.offset : end])
        return _decompress_entry(raw, entry.compression_method, entry.uncompressed_size)
