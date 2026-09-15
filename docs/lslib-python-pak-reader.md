# Spécifications Techniques : Lecteur Python Natif d'Archives `.pak` (BG3)

Document technique à destination de l'Agent IA / Développeur pour l'implémentation de l'**Option A** (Module Python Natif) dédié à l'extraction ultra-rapide des métadonnées des mods Baldur's Gate 3.

---

## 1. Contexte & Objectif

L'application doit identifier de manière 100% fiable chaque mod `.pak` BG3 en lisant son `UUID` et son `Name` réels embarqués dans son fichier `meta.lsx` (ou `meta.lsf`).

### Problème actuel (`Divine.exe`)
* **Lenteur importante :** Lancer un sous-processus CLI .NET (`Divine.exe`) crée un surcoût d'I/O et de démarrage de la VM .NET.
* **Dépendances lourdes :** Exige d'embarquer les binaires de LSLib / `Divine.exe` et nécessite l'installation du runtime .NET par l'utilisateur.

### Solution retenue (Option A : Module Python Pur)
Développer un module léger `pak_reader.py` basé sur `mmap`, `struct` et `lz4` qui effectue une **lecture partielle (Lazy Loading)** :
1. Projection mémoire du `.pak` sans tout charger en RAM (`mmap`).
2. Décompression uniquement de la table des matières (Index).
3. Décompression uniquement du fichier `meta.lsx` / `meta.lsf`.
4. Extraction ciblée de l'`UUID` et du `Name`.

**Performance visée :** < 5 ms par fichier `.pak` (contre 300ms à 1s actuellement via `Divine.exe`).

---

## 2. Spécifications du Format LSPK (v16 & v18)

Les fichiers `.pak` de Baldur's Gate 3 utilisent la signature binaire `LSPK` (Little-Endian).

### 2.1 En-tête (Header)

* **Magic Bytes (4 octets) :** `0x4B50534C` (`LSPK` en ASCII).
* **Version (4 octets) :** `16` (`0x10`) ou `18` (`0x12`).
* **Offset de l'Index (8 octets / uint64) :** Position binaire où commence la Table des Matières.
* **Taille compressée de l'Index (4 octets / uint32) :** Taille du bloc de l'Index sur disque.
* **Taille décompressée de l'Index (4 octets / uint32) :** Taille brute de l'Index.

### 2.2 Table des Matières (Index)

L'Index contient la liste de tous les fichiers inclus dans l'archive. Ce bloc est compressé en **LZ4**.

Chaque entrée de fichier dans l'Index contient :
* **Path / Name :** Chemin relatif dans l'archive (ex: `Mods/MyModName/meta.lsx` ou `Mods/MyModName/meta.lsf`).
* **Offset (uint64) :** Position de départ des données du fichier dans le `.pak`.
* **SizeOnDisk (uint32) :** Taille compressée.
* **UncompressedSize (uint32) :** Taille réelle décompressée.
* **Flags / Compression (uint8) :**
  * `0x00` = Non compressé
  * `0x01` = zlib
  * `0x02` = LZ4

---

## 3. Algorithme d'Extraction Step-by-Step

```
[ Fichier .pak ]
       │
       ├── 1. Projection mémoire (`mmap.mmap`)
       ├── 2. Valider les Magic Bytes (`LSPK`) et lire la version (v16/v18)
       ├── 3. Seek vers l'Offset de l'Index & décompresser le bloc via `lz4.block.decompress`
       ├── 4. Parcourir les entrées de l'Index et localiser `meta.lsx` ou `meta.lsf`
       ├── 5. Lire et décompresser UNIQUEMENT les octets de ce fichier meta
       └── 6. Parser les données (XML pour `.lsx` ou binaire pour `.lsf`) -> Retourner (UUID, Name)
```

---

## 4. Guide d'Implémentation Python (`pak_reader.py`)

### 4.1 Dépendances
* **Standard Python :** `mmap`, `struct`, `xml.etree.ElementTree`, `re`, `pathlib`
* **PyPI :** `lz4` (`pip install lz4`)

### 4.2 Prototype de Code pour l'Agent IA

```python
import mmap
import struct
import re
import xml.etree.ElementTree as ET
import lz4.block

LSPK_HEADER_MAGIC = b"LSPK"

def parse_meta_lsx(xml_bytes: bytes) -> dict:
    """Parse le XML meta.lsx et extrait les attributs UUID et Name."""
    root = ET.fromstring(xml_bytes)
    info = {"uuid": None, "name": None}
    
    for node in root.iter("attribute"):
        node_id = node.attrib.get("id")
        if node_id == "UUID":
            info["uuid"] = node.attrib.get("value")
        elif node_id in ("Name", "Folder"):
            if not info["name"]:
                info["name"] = node.attrib.get("value")
                
    return info

def parse_meta_lsf(lsf_bytes: bytes) -> dict:
    """Parse le format binaire LSF via regex fallback sur la table des chaînes."""
    uuid_match = re.search(rb'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', lsf_bytes)
    uuid = uuid_match.group(0).decode('utf-8') if uuid_match else None
    
    return {"uuid": uuid, "name": None}

def extract_mod_info_from_pak(pak_path: str) -> dict:
    with open(pak_path, "rb") as f:
        # 1. Memory mapping (Zero-Copy)
        with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            # 2. Vérification du Header
            magic = mm[0:4]
            if magic != LSPK_HEADER_MAGIC:
                raise ValueError("Format PAK invalide (Magic bytes incorrects)")
            
            version = struct.unpack("<I", mm[4:8])[0]
            if version not in (16, 18):
                raise ValueError(f"Version LSPK non supportée: {version}")
            
            # Read Offset & Compressed Size of Index (Format V16/V18)
            index_offset = struct.unpack("<Q", mm[8:16])[0]
            index_size_compressed = struct.unpack("<I", mm[16:20])[0]
            index_size_uncompressed = struct.unpack("<I", mm[20:24])[0]
            
            # 3. Décompression de l'Index
            compressed_index_bytes = mm[index_offset : index_offset + index_size_compressed]
            index_bytes = lz4.block.decompress(
                compressed_index_bytes, 
                uncompressed_size=index_size_uncompressed
            )
            
            # 4. Parsing de l'Index pour localiser meta.lsx / meta.lsf
            # (Implémenter la recherche du bloc de fichier dans index_bytes)
            meta_entry = parse_index_and_find_meta(index_bytes, version)
            if not meta_entry:
                raise FileNotFoundError("Aucun fichier meta.lsx ou meta.lsf trouvé dans le .pak")
            
            # 5. Extraction du fichier meta
            file_data = mm[meta_entry['offset'] : meta_entry['offset'] + meta_entry['size_on_disk']]
            if meta_entry['compression'] == 2:  # LZ4
                meta_content = lz4.block.decompress(file_data, uncompressed_size=meta_entry['size_uncompressed'])
            elif meta_entry['compression'] == 1:  # zlib
                import zlib
                meta_content = zlib.decompress(file_data)
            else:
                meta_content = file_data
                
            # 6. Extraction de l'UUID et du Name
            if meta_entry['name'].endswith('.lsx'):
                return parse_meta_lsx(meta_content)
            else:
                return parse_meta_lsf(meta_content)
```

---

## 5. Intégration & Fallback

1. **Remplacement de `Divine.exe` :**
   Dans `compat_framework.py`, remplacer les appels `subprocess.run(["Divine.exe", ...])` par le nouvel appel natif `pak_reader.extract_mod_info_from_pak(pak_file)`.

2. **Gestion des Exceptions / Fallback :**
   Si la lecture native échoue (ex: version `.pak` inattendue ou fichier corrompu), capturer l'exception et exécuter en **fallback** l'ancien appel vers `Divine.exe`.

3. **Optimisation de l'Inventaire :**
   Mettre à jour `inventory._match_pak_to_archive` pour utiliser `pak_reader` lors du scan initial du dossier de mods, garantissant une association exacte et instantanée entre les archives et les fichiers `.pak`.
