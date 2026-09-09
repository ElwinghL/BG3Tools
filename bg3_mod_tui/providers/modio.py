"""Client mod.io pour Baldur's Gate 3.

Utilise l'API utilisateur (https://u-{MOD_IO_USER_ID}.modapi.io/v1) décrite
dans `.env.example`, qui permet de lister/télécharger directement les mods
auxquels le compte est abonné (`/me/subscribed`) sans avoir besoin du
Game ID BG3 sur mod.io.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class ModIOAPIError(RuntimeError):
    pass


@dataclass
class ModIOMod:
    mod_id: int
    name: str
    summary: str
    download_url: str | None


class ModIOClient:
    def __init__(
        self,
        api_key: str,
        *,
        user_id: str | None = None,
        api_base: str | None = None,
        access_token: str | None = None,
    ) -> None:
        if not api_key:
            raise ModIOAPIError("Clé API mod.io manquante (MODIO_API_KEY).")
        self._api_key = api_key
        self._access_token = access_token
        if api_base:
            self._base = api_base.rstrip("/")
        elif user_id:
            self._base = f"https://u-{user_id}.modapi.io/v1"
        else:
            raise ModIOAPIError(
                "Renseigne MOD_IO_USER_ID ou MODIO_API_BASE dans le fichier .env."
            )

    def _client(self) -> httpx.Client:
        headers = {"Accept": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        return httpx.Client(base_url=self._base, headers=headers, timeout=15)

    def _params(self, **extra: str) -> dict:
        params = {"api_key": self._api_key}
        params.update(extra)
        return params

    def subscribed_mods(self) -> list[ModIOMod]:
        with self._client() as client:
            resp = client.get("/me/subscribed", params=self._params())
        if resp.status_code != 200:
            raise ModIOAPIError(
                f"Erreur lors de la récupération des mods abonnés ({resp.status_code})."
            )
        mods = []
        for entry in resp.json().get("data", []):
            modfile = entry.get("modfile") or {}
            download = modfile.get("download", {}) if modfile else {}
            mods.append(
                ModIOMod(
                    mod_id=entry["id"],
                    name=entry.get("name", f"Mod {entry['id']}"),
                    summary=entry.get("summary", ""),
                    download_url=download.get("binary_url"),
                )
            )
        return mods
