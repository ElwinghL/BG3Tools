"""Téléchargement/mise à jour des outils tiers listés dans TOOLS.md, et
découverte des exécutables installés sous Tools/.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from bg3_mod_tui.archives import ArchiveError, extract_archive

LogFn = Callable[[str], None]

_TABLE_ROW_RE = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<local>[^|]+?)\s*\|\s*(?P<source>[^|]+?)\s*\|\s*$"
)
_GITHUB_REPO_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s]+?)(?:/|\s|$)")
_BACKTICKED_PATH_RE = re.compile(r"`([^`]+)`")


class ToolsError(RuntimeError):
    pass


@dataclass
class ToolEntry:
    name: str
    local_dir: str | None
    github_owner: str | None
    github_repo: str | None


def parse_tools_table(path: Path) -> list[ToolEntry]:
    """Parse le tableau markdown de TOOLS.md (colonnes Outil / Dossier
    local / Dépôt source)."""
    if not path.is_file():
        raise ToolsError(f"Fichier introuvable : {path}")

    entries: list[ToolEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _TABLE_ROW_RE.match(line.strip())
        if not match:
            continue
        name = match.group("name").strip()
        local_raw = match.group("local").strip()
        source_raw = match.group("source").strip()
        if name.lower() == "outil" or set(name) <= {"-"}:
            continue

        local_match = _BACKTICKED_PATH_RE.search(local_raw)
        local_dir = local_match.group(1).rstrip("/") if local_match else None

        gh_match = _GITHUB_REPO_RE.search(source_raw)
        owner, repo = (gh_match.group(1), gh_match.group(2)) if gh_match else (None, None)

        entries.append(ToolEntry(name=name, local_dir=local_dir, github_owner=owner, github_repo=repo))

    return entries


def _github_asset_url(owner: str, repo: str) -> tuple[str, str]:
    """Retourne (nom, url) du meilleur asset à télécharger : le premier
    asset .zip d'une release GitHub, ou à défaut l'archive source zip."""
    with httpx.Client(timeout=15, headers={"Accept": "application/vnd.github+json"}) as client:
        resp = client.get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
        if resp.status_code == 200:
            data = resp.json()
            for asset in data.get("assets", []):
                if asset.get("name", "").lower().endswith(".zip"):
                    return asset["name"], asset["browser_download_url"]
            if data.get("zipball_url"):
                return f"{repo}-{data.get('tag_name', 'latest')}.zip", data["zipball_url"]

        resp = client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if resp.status_code != 200:
            raise ToolsError(f"Dépôt GitHub introuvable : {owner}/{repo} ({resp.status_code}).")
        default_branch = resp.json().get("default_branch", "main")
        return (
            f"{repo}-{default_branch}.zip",
            f"https://github.com/{owner}/{repo}/archive/refs/heads/{default_branch}.zip",
        )


def download_and_extract_tool(
    entry: ToolEntry, project_root: Path, *, log: LogFn = lambda _m: None
) -> None:
    """Télécharge et extrait un outil GitHub dans
    `project_root/<entry.local_dir>` (ex: "Tools/xxx", tel que déclaré dans
    TOOLS.md). Ignore silencieusement (avec message) les entrées sans
    dossier local ou sans dépôt GitHub (installation manuelle requise, ex:
    Native Mod Loader)."""
    if entry.local_dir is None:
        log(f"[{entry.name}] pas de dossier local défini, ignoré.")
        return
    if entry.github_owner is None or entry.github_repo is None:
        log(f"[{entry.name}] pas de dépôt GitHub, installation manuelle requise.")
        return

    dest_dir = project_root / entry.local_dir

    try:
        name, url = _github_asset_url(entry.github_owner, entry.github_repo)
    except ToolsError as exc:
        log(f"[{entry.name}] {exc}")
        return

    with tempfile.TemporaryDirectory(prefix="bg3modtools_tool_") as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / name
        log(f"[{entry.name}] téléchargement de {name}...")
        try:
            with httpx.stream("GET", url, timeout=30, follow_redirects=True) as resp:
                resp.raise_for_status()
                with archive_path.open("wb") as fh:
                    for chunk in resp.iter_bytes(65536):
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            log(f"[{entry.name}] échec du téléchargement : {exc}")
            return

        extract_dir = tmp_path / "extracted"
        try:
            extract_archive(archive_path, extract_dir)
        except ArchiveError as exc:
            log(f"[{entry.name}] échec d'extraction : {exc}")
            return

        # Les archives GitHub (zipball / source zip) contiennent un seul
        # dossier racine ("repo-branche/") : on en prend le contenu direct.
        top_level = list(extract_dir.iterdir())
        source_dir = top_level[0] if len(top_level) == 1 and top_level[0].is_dir() else extract_dir

        dest_dir.mkdir(parents=True, exist_ok=True)
        for item in source_dir.iterdir():
            target = dest_dir / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))

        log(f"[{entry.name}] installé dans {dest_dir}.")


def find_executables(tools_root: Path) -> list[Path]:
    """Liste les exécutables Windows (.exe) présents sous `tools_root`."""
    if not tools_root.is_dir():
        return []
    return sorted(tools_root.rglob("*.exe"))
