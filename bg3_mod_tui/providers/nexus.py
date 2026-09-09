"""Client Nexus Mods pour Baldur's Gate 3.

Doc API : https://app.swaggerhub.com/apis-docs/NexusMods/nexus-mods_public_api_params_in_form_data/1.0
Le téléchargement direct via l'API (`download_link.json`) nécessite un
compte Nexus Premium. Sans compte Premium, l'API renvoie une erreur et le
téléchargement doit passer par le lien "Mod Manager Download" (nxm://) du
site, que ce TUI ne peut pas contourner.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

API_BASE = "https://api.nexusmods.com/v1"
GAME_DOMAIN = "baldursgate3"


class NexusAPIError(RuntimeError):
    pass


@dataclass
class NexusMod:
    mod_id: int
    name: str
    version: str
    summary: str


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
