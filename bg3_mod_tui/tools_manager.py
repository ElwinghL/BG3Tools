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

# Fichier marqueur écrit dans le dossier de chaque outil après installation,
# contenant la version installée (tag de release, ou hash court du dernier
# commit pour un dépôt sans release) — permet à une prochaine "MAJ des
# outils" de savoir si un nouveau téléchargement est nécessaire plutôt que
# de retélécharger/écraser à chaque fois, peu importe l'état actuel.
VERSION_MARKER_NAME = ".bg3modtools_version"


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


@dataclass
class ToolRelease:
    asset_name: str
    download_url: str
    version: str
    """Tag de la release GitHub, ou hash court du dernier commit du
    répertoire par défaut pour un dépôt sans release — sert uniquement à
    détecter si l'outil déjà installé est à jour, pas affiché comme un
    vrai numéro de version sémantique."""


def _github_release(owner: str, repo: str) -> ToolRelease:
    """Retourne le meilleur asset à télécharger (premier .zip d'une
    release GitHub, ou à défaut l'archive source zip) avec sa version."""
    with httpx.Client(timeout=15, headers={"Accept": "application/vnd.github+json"}) as client:
        resp = client.get(f"https://api.github.com/repos/{owner}/{repo}/releases/latest")
        if resp.status_code == 200:
            data = resp.json()
            tag = data.get("tag_name") or "latest"
            for asset in data.get("assets", []):
                if asset.get("name", "").lower().endswith(".zip"):
                    return ToolRelease(asset["name"], asset["browser_download_url"], tag)
            if data.get("zipball_url"):
                return ToolRelease(f"{repo}-{tag}.zip", data["zipball_url"], tag)

        resp = client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if resp.status_code != 200:
            raise ToolsError(f"Dépôt GitHub introuvable : {owner}/{repo} ({resp.status_code}).")
        default_branch = resp.json().get("default_branch", "main")

        # Pas de release : la "version" est le hash du dernier commit de la
        # branche par défaut, seul moyen de détecter un changement réel
        # (sinon rien ne distinguerait deux téléchargements du même zip
        # source à des moments différents).
        commit_resp = client.get(f"https://api.github.com/repos/{owner}/{repo}/commits/{default_branch}")
        version = commit_resp.json()["sha"][:12] if commit_resp.status_code == 200 else default_branch

        return ToolRelease(
            f"{repo}-{default_branch}.zip",
            f"https://github.com/{owner}/{repo}/archive/refs/heads/{default_branch}.zip",
            version,
        )


def _installed_version(dest_dir: Path) -> str | None:
    version_file = dest_dir / VERSION_MARKER_NAME
    if not version_file.is_file():
        return None
    try:
        return version_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


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
        release = _github_release(entry.github_owner, entry.github_repo)
    except ToolsError as exc:
        log(f"[{entry.name}] {exc}")
        return

    installed = _installed_version(dest_dir)
    if installed == release.version:
        log(f"[{entry.name}] déjà à jour ({release.version}).")
        return
    if installed:
        log(f"[{entry.name}] mise à jour : {installed} -> {release.version}.")
    else:
        log(f"[{entry.name}] installation ({release.version})...")

    with tempfile.TemporaryDirectory(prefix="bg3modtools_tool_") as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / release.asset_name
        log(f"[{entry.name}] téléchargement de {release.asset_name}...")
        try:
            with httpx.stream("GET", release.download_url, timeout=30, follow_redirects=True) as resp:
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

        (dest_dir / VERSION_MARKER_NAME).write_text(release.version, encoding="utf-8")
        log(f"[{entry.name}] installé dans {dest_dir} ({release.version}).")


def find_executables(tools_root: Path) -> list[Path]:
    """Liste les exécutables Windows (.exe) présents sous `tools_root`."""
    if not tools_root.is_dir():
        return []
    return sorted(tools_root.rglob("*.exe"))
