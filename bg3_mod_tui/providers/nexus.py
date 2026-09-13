"""Client Nexus Mods pour Baldur's Gate 3.

Doc API : https://app.swaggerhub.com/apis-docs/NexusMods/nexus-mods_public_api_params_in_form_data/1.0
Le téléchargement direct via l'API (`download_link.json`) nécessite un
compte Nexus Premium. Sans compte Premium, l'API renvoie une erreur et le
téléchargement doit passer par le lien "Mod Manager Download" (nxm://) du
site, que ce TUI ne peut pas contourner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

API_BASE = "https://api.nexusmods.com/v1"
GAME_DOMAIN = "baldursgate3"

_MOD_URL_RE = re.compile(r"nexusmods\.com/baldursgate3/mods/(\d+)")


def parse_mod_links_file(path: Path) -> list[int]:
    """Extrait les identifiants de mods Nexus (Baldur's Gate 3) d'un fichier
    listant une URL de mod par ligne (voir `nexus_links_to_add.md`)."""
    if not path.is_file():
        raise NexusAPIError(f"Fichier de liens introuvable : {path}")
    mod_ids: list[int] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _MOD_URL_RE.search(line)
        if match:
            mod_ids.append(int(match.group(1)))
    return mod_ids


def remove_mod_links(path: Path, mod_ids: set[int]) -> None:
    """Retire de `path` les lignes correspondant aux mods de `mod_ids`
    (les autres lignes, y compris vides ou non reconnues, sont conservées)."""
    if not mod_ids or not path.is_file():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = []
    for line in lines:
        match = _MOD_URL_RE.search(line)
        if match and int(match.group(1)) in mod_ids:
            continue
        kept.append(line)
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")


class NexusAPIError(RuntimeError):
    pass


@dataclass
class NexusMod:
    mod_id: int
    name: str
    version: str
    summary: str


@dataclass
class NexusFileVariant:
    """Une variante de fichier distincte d'un mod Nexus (voir
    `NexusClient.latest_file_variants`) — `name` est le nom de variante tel
    qu'affiché sur Nexus (ex: "1 - Karlach normal NSFW"), à distinguer de
    `file_name` (nom du fichier zip/7z réellement téléchargé). `version`
    est la version PROPRE à cette variante, pas celle de `NexusMod.version`
    qui ne reflète que la page mod (généralement le fichier "principal")."""

    file_id: int
    file_name: str
    name: str
    version: str


class NexusClient:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise NexusAPIError("Clé API Nexus Mods manquante (NEXUS_API_KEY).")
        self._headers = {"apikey": api_key, "Accept": "application/json"}

    def validate(self) -> dict:
        """Vérifie la clé API et retourne les infos du compte."""
        with httpx.Client(base_url=API_BASE, headers=self._headers, timeout=15) as client:
            resp = client.get("/users/validate.json")
        if resp.status_code != 200:
            raise NexusAPIError(f"Clé API Nexus invalide ou erreur ({resp.status_code}).")
        return resp.json()

    def tracked_mods(self) -> list[NexusMod]:
        with httpx.Client(base_url=API_BASE, headers=self._headers, timeout=15) as client:
            resp = client.get("/user/tracked_mods.json")
        if resp.status_code != 200:
            raise NexusAPIError(f"Erreur lors de la récupération des mods suivis ({resp.status_code}).")
        mods = []
        for entry in resp.json():
            if entry.get("domain_name") != GAME_DOMAIN:
                continue
            mod_info = self.mod_info(entry["mod_id"])
            mods.append(mod_info)
        return mods

    def mod_info(self, mod_id: int) -> NexusMod:
        with httpx.Client(base_url=API_BASE, headers=self._headers, timeout=15) as client:
            resp = client.get(f"/games/{GAME_DOMAIN}/mods/{mod_id}.json")
        if resp.status_code != 200:
            raise NexusAPIError(f"Mod Nexus {mod_id} introuvable ({resp.status_code}).")
        data = resp.json()
        return NexusMod(
            mod_id=data["mod_id"],
            name=data.get("name", f"Mod {mod_id}"),
            version=data.get("version", ""),
            summary=data.get("summary", ""),
        )

    def latest_file_variants(self, mod_id: int) -> list[NexusFileVariant]:
        """Retourne, pour chaque variante distincte d'un mod (son `name`
        Nexus — ex: différentes couleurs/options proposées en fichiers
        'OPTIONAL', ou des fichiers sans rapport entre eux partageant la
        même page mod — voir `mod_pipeline.check_nexus_updates`), le
        fichier le plus récent, `version` INCLUSE (propre à cette variante,
        contrairement à `NexusMod.version` qui ne reflète que la page mod).

        Une même variante peut avoir plusieurs uploads dans le temps (une
        'UPDATE' remplaçant une 'MAIN' du même nom) : on ne garde que le
        plus récent de chacune, jamais un vieil upload. Des variantes avec
        des noms différents (ex: 'MAIN' + plusieurs 'OPTIONAL' distinctes)
        sont en revanche toutes retournées, chacune à sa version la plus
        récente — le tri entre elles (lesquelles garder dans le load
        order) se fait ensuite manuellement. Seuls 'OLD_VERSION' et
        'MISCELLANEOUS' sont exclus. Lève `NexusAPIError` si aucun fichier
        n'est disponible."""
        with httpx.Client(base_url=API_BASE, headers=self._headers, timeout=15) as client:
            resp = client.get(f"/games/{GAME_DOMAIN}/mods/{mod_id}/files.json")
        if resp.status_code != 200:
            raise NexusAPIError(
                f"Impossible de récupérer les fichiers du mod {mod_id} ({resp.status_code})."
            )
        files = resp.json().get("files", [])
        eligible = [f for f in files if f.get("category_name") in ("MAIN", "UPDATE", "OPTIONAL")]
        candidates = eligible or files
        if not candidates:
            raise NexusAPIError(f"Aucun fichier disponible pour le mod {mod_id}.")

        by_variant: dict[str, dict] = {}
        for f in candidates:
            key = f.get("name") or f.get("file_name") or str(f.get("file_id"))
            current = by_variant.get(key)
            if current is None or f.get("uploaded_timestamp", 0) > current.get("uploaded_timestamp", 0):
                by_variant[key] = f

        return [
            NexusFileVariant(
                file_id=f["file_id"],
                file_name=f.get("file_name", f"mod_{mod_id}.zip"),
                name=f.get("name") or f.get("file_name", ""),
                version=f.get("version", ""),
            )
            for f in by_variant.values()
        ]

    def latest_files(self, mod_id: int) -> list[tuple[int, str]]:
        """Repli historique de `latest_file_variants` (mêmes filtres/dédup),
        sans la version — gardé pour les appelants qui n'ont besoin que de
        `(file_id, file_name)` (téléchargement)."""
        return [(v.file_id, v.file_name) for v in self.latest_file_variants(mod_id)]

    def download_link(self, mod_id: int, file_id: int) -> str:
        """Nécessite un compte Nexus Premium ; sinon lève NexusAPIError."""
        with httpx.Client(base_url=API_BASE, headers=self._headers, timeout=15) as client:
            resp = client.get(
                f"/games/{GAME_DOMAIN}/mods/{mod_id}/files/{file_id}/download_link.json"
            )
        if resp.status_code != 200:
            raise NexusAPIError(
                "Téléchargement direct indisponible (compte non-Premium ou "
                f"erreur API : {resp.status_code}). Utilise le lien "
                "'Mod Manager Download' depuis le site Nexus Mods."
            )
        links = resp.json()
        if not links:
            raise NexusAPIError("Aucun lien de téléchargement disponible.")
        return links[0]["URI"]
