"""Validateur `.pak` standalone, en Python pur, sans Divine.exe — port du
"check" de structure que fait `divine.exe -a extract-package` (ou l'action
équivalente de LSLib) en passant en revue chaque entrée d'un .pak : ce
module s'appuie entièrement sur le lecteur natif `pak_reader` (mmap +
parsing LSPK) déjà utilisé pour la lecture d'identité (`pak_metadata.py`),
pas de réimplémentation du parsing binaire ici.

Principe : ouvrir le .pak (header + table des fichiers), puis tenter de
lire/décompresser un échantillon de ses entrées — toute exception levée à
ce stade (`pak_reader.PakReaderError` : décompression échouée, offset hors
bornes, taille décompressée incohérente...) est capturée et traduite en
détail d'erreur pour cette entrée, sans faire remonter l'exception : un
.pak "invalide" au sens de ce module n'est pas un crash, c'est un résultat
structuré (voir `PakValidationResult`/`validate_paks`).

LIMITES IMPORTANTES (à lire avant de faire confiance à ce validateur) :

1. Hérite intégralement des incertitudes non vérifiées empiriquement de
   `pak_reader` (voir sa docstring) : aucun vrai .pak BG3 n'était
   disponible dans l'environnement de développement de ce module pour
   valider le parsing contre un fichier réel — en particulier la
   reconstruction de l'offset 48 bits (v18) et le bitmask de méthode de
   compression par entrée. Un .pak parfaitement valide pourrait donc, en
   théorie, être signalé à tort comme invalide si une de ces hypothèses de
   format est erronée (et inversement, un vrai .pak corrompu pourrait ne
   pas être détecté si l'hypothèse erronée "absorbe" la corruption sans
   lever d'exception). Ce n'est PAS un remplacement fiable, one-to-one, de
   `divine.exe -a extract-package` ou d'un futur "validate-package" —
   seulement un check rapide de structure/intégrité, en repli/complément.
2. **N'exclut PAS de repli automatique sur Divine.exe** : contrairement à
   `pak_metadata.read_pak_identity`, ce module ne fait *aucun* repli — une
   erreur de lecture native ici est le résultat final rapporté (c'est le
   but : signaler que le .pak est structurellement invalide, ou que ce
   lecteur natif n'a pas su le lire, sans distinguer les deux cas plus
   précisément qu'avec le message d'erreur capturé).
3. **Échantillonnage, pas exhaustivité garantie sur les gros .pak** : lire
   et décompresser *toutes* les entrées d'un .pak de plusieurs Go (assets
   BG3) serait lent et defeat le but d'un check rapide. Par défaut, ce
   module lit systématiquement toutes les entrées jusqu'à
   `DEFAULT_MAX_ENTRIES_CHECKED` (voir sa docstring pour le choix de la
   valeur) ; au-delà, il échantillonne un sous-ensemble réparti sur toute
   la table des fichiers (pas seulement les premières entrées) pour
   garder une chance de détecter une corruption localisée n'importe où
   dans le .pak. Un .pak marqué "valide" par ce module signifie donc
   "l'échantillon lu est cohérent", pas "chaque octet du .pak est intact".
4. **Ne fait STRICTEMENT rien d'autre que cette validation structurelle** :
   ce module ne génère PAS `modsettings.lsx`, ne modifie PAS l'ordre de
   charge d'un profil, et ne lance PAS le jeu (BG3) ni aucun de ses
   processus — contrairement à d'autres actions du TUI qui touchent à ces
   aspects (voir `screens/actions.py`, boutons "Sync. modsettings.lsx" et
   consorts). Il se contente d'ouvrir le(s) .pak en lecture seule (mmap) et
   d'en lire le contenu en mémoire, rien n'est écrit sur disque."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bg3_mod_tui.pak_reader import PakArchive, PakFileEntry, PakReaderError

# Nombre d'entrées lues/décompressées avant de basculer sur un
# échantillonnage réparti plutôt qu'un check exhaustif — choisi comme
# compromis pragmatique (pas de mesure de performance sur un vrai .pak BG3
# disponible, voir limite documentée ci-dessus) : assez élevé pour couvrir
# entièrement la quasi-totalité des mods (qui ont rarement plus de
# quelques centaines de fichiers), assez bas pour qu'un .pak "vanilla-like"
# de plusieurs dizaines de milliers d'entrées (gros mods de contenu) ne
# bloque pas l'UI plusieurs minutes.
DEFAULT_MAX_ENTRIES_CHECKED = 500


@dataclass(frozen=True)
class PakValidationResult:
    """Résultat de la validation d'un seul .pak — voir `validate_pak`."""

    path: Path
    valid: bool
    num_entries: int
    checked_entries: int
    errors: list[str] = field(default_factory=list)


def _select_sample(entries: list[PakFileEntry], max_entries: int) -> list[PakFileEntry]:
    """Sélectionne jusqu'à `max_entries` entrées à vérifier, réparties sur
    toute la table des fichiers plutôt que les `max_entries` premières —
    une corruption localisée en fin de .pak (ex: dernière entrée tronquée)
    resterait sinon invisible sur un gros .pak. Retourne toutes les
    entrées si `len(entries) <= max_entries` (ou si `max_entries <= 0`,
    interprété comme "pas de limite")."""
    if max_entries <= 0 or len(entries) <= max_entries:
        return list(entries)
    step = len(entries) / max_entries
    indices = sorted({int(i * step) for i in range(max_entries)})
    return [entries[i] for i in indices]


def validate_pak(
    path: Path, *, max_entries_checked: int = DEFAULT_MAX_ENTRIES_CHECKED
) -> PakValidationResult:
    """Valide la structure d'un seul .pak : ouvre `path` via
    `pak_reader.PakArchive` (header + table des fichiers), puis lit/
    décompresse un échantillon de ses entrées (voir `_select_sample` et la
    limite documentée sur l'échantillonnage dans ce module). Ne lève
    jamais d'exception pour un .pak illisible/corrompu — le résultat
    (`PakValidationResult.valid=False` + `errors`) porte l'information.

    Erreurs détectées :
    - échec d'ouverture/parsing du header ou de la table des fichiers
      (`PakReaderError` sur `PakArchive.open`) ;
    - échec de décompression d'une entrée (`PakReaderError` sur
      `PakArchive.read`, ex: LZ4/zstd/zlib invalide) ;
    - offset d'une entrée hors des bornes du fichier mappé (également
      `PakReaderError`, levée par `PakArchive.read`) ;
    - taille décompressée obtenue incohérente avec `UncompressedSize`
      annoncé dans la table des fichiers (corruption silencieuse que la
      décompression seule ne détecterait pas forcément)."""
    errors: list[str] = []
    try:
        with PakArchive.open(path) as pak:
            entries = pak.entries
            sample = _select_sample(entries, max_entries_checked)
            for entry in sample:
                try:
                    content = pak.read(entry)
                except PakReaderError as exc:
                    errors.append(f"{entry.name} : {exc}")
                    continue
                if len(content) != entry.uncompressed_size:
                    errors.append(
                        f"{entry.name} : taille décompressée incohérente "
                        f"(annoncée {entry.uncompressed_size}, obtenue {len(content)})"
                    )
    except PakReaderError as exc:
        return PakValidationResult(
            path=path, valid=False, num_entries=0, checked_entries=0, errors=[str(exc)]
        )
    return PakValidationResult(
        path=path,
        valid=not errors,
        num_entries=len(entries),
        checked_entries=len(sample),
        errors=errors,
    )


def validate_paks(
    paths: list[Path], *, max_entries_checked: int = DEFAULT_MAX_ENTRIES_CHECKED
) -> dict[str, list]:
    """Valide une liste de .pak et retourne un rapport structuré, dans le
    style `report: dict[str, list]` déjà utilisé ailleurs dans le projet
    (voir `mod_pipeline.check_nexus_updates`, `inventory.find_orphaned_archives`) :

        {
            "valid": [PakValidationResult, ...],
            "invalid": [PakValidationResult, ...],
        }

    Chaque `PakValidationResult` (valide ou non) porte `path`, `valid`,
    `num_entries`/`checked_entries` et le détail des erreurs éventuelles
    (`errors`) — pas seulement un statut binaire. Ne lève jamais
    d'exception : un .pak en échec finit dans `"invalid"` avec son détail
    d'erreur, les autres continuent d'être traités."""
    valid: list[PakValidationResult] = []
    invalid: list[PakValidationResult] = []
    for path in paths:
        result = validate_pak(path, max_entries_checked=max_entries_checked)
        (valid if result.valid else invalid).append(result)
    return {"valid": valid, "invalid": invalid}
