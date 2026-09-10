"""Téléchargement/mise à jour des outils tiers listés dans TOOLS.md, et
découverte des exécutables installés sous Tools/.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from bg3_mod_tui.archives import ArchiveError, extract_archive, is_supported_archive

LogFn = Callable[[str], None]

_TABLE_ROW_RE = re.compile(
    r"^\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<local>[^|]+?)\s*\|\s*(?P<source>[^|]+?)\s*\|\s*$"
)
_GITHUB_REPO_RE = re.compile(r"github\.com/([^/\s]+)/([^/\s]+?)(?:/|\s|$)")
_NEXUS_MOD_RE = re.compile(r"nexusmods\.com/baldursgate3/mods/(\d+)")
_BACKTICKED_PATH_RE = re.compile(r"`([^`]+)`")

# Dossier où l'utilisateur dépose l'archive téléchargée à la main pour un
# outil Nexus (pas d'API de téléchargement direct sans compte Premium —
# voir bg3_mod_tui/providers/nexus.py) : la racine de Tools/ elle-même,
# là où un tel outil finit déjà manuellement dans la pratique.
NEXUS_TOOL_DOWNLOAD_DIR_NAME = "Tools"
# Une fois installée, l'archive est déplacée ici plutôt que supprimée
# (comme les archives de mods déjà traitées) pour ne pas relancer son
# installation à chaque "MAJ des outils" ni perdre le fichier source.
NEXUS_TOOL_ARCHIVE_SUBDIR = "Archives_installees/_installees"

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
    nexus_mod_id: int | None = None


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

        nexus_match = _NEXUS_MOD_RE.search(source_raw) if owner is None else None
        nexus_mod_id = int(nexus_match.group(1)) if nexus_match else None

        entries.append(
            ToolEntry(
                name=name,
                local_dir=local_dir,
                github_owner=owner,
                github_repo=repo,
                nexus_mod_id=nexus_mod_id,
            )
        )

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


def _github_release(owner: str, repo: str) -> ToolRelease | None:
    """Retourne le meilleur asset à télécharger (premier .zip d'une
    release GitHub, ou à défaut l'archive source zip de cette release)
    avec sa version. `None` si le dépôt n'a aucune release exploitable —
    dans ce cas seule la source (toujours suivie comme sous-module git,
    voir `_add_or_update_git_submodule`) est installée, sans sous-dossier
    de release précompilée. Lève `ToolsError` si le dépôt lui-même est
    introuvable."""
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
            return None

        resp = client.get(f"https://api.github.com/repos/{owner}/{repo}")
        if resp.status_code != 200:
            raise ToolsError(f"Dépôt GitHub introuvable : {owner}/{repo} ({resp.status_code}).")
        return None


def _run_git(args: list[str], *, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _is_registered_submodule(project_root: Path, local_dir: str) -> bool:
    """Vrai si `local_dir` est déjà déclaré comme sous-module dans
    `.gitmodules` à la racine de `project_root`."""
    gitmodules = project_root / ".gitmodules"
    if not gitmodules.is_file():
        return False
    check = _run_git(["config", "--file", ".gitmodules", "--get-regexp", r"\.path$"], cwd=project_root)
    if check.returncode != 0:
        return False
    return any(line.strip().endswith(f" {local_dir}") for line in check.stdout.splitlines())


def _add_or_update_git_submodule(owner: str, repo: str, local_dir: str, project_root: Path, *, log: LogFn) -> str:
    """Déclare (première fois, `git submodule add`) ou met à jour
    (`git submodule update --remote`, sur la branche par défaut du
    remote) `local_dir` comme sous-module git du dépôt BG3Tools lui-même
    — un vrai sous-dépôt épinglé à un commit précis dans notre historique,
    plutôt qu'une simple archive téléchargée, pour suivre un dépôt qu'on
    développe/dont on dépend activement (ex: bg3rustpaklib, mais aussi les
    autres outils GitHub de TOOLS.md). N'effectue aucun commit dans
    BG3Tools : `git submodule add`/`update --remote` modifient
    `.gitmodules` et l'index (le gitlink épinglé), à committer
    explicitement plus tard. Retourne le hash court du commit HEAD du
    sous-module après l'opération ; lève `ToolsError` en cas d'échec
    d'une commande git."""
    url = f"https://github.com/{owner}/{repo}.git"
    dest_dir = project_root / local_dir

    if _is_registered_submodule(project_root, local_dir):
        log(f"[{repo}] sous-module existant, mise à jour (submodule update --remote)...")
        update = _run_git(
            ["submodule", "update", "--remote", "--checkout", "--", local_dir],
            cwd=project_root,
            timeout=300,
        )
        if update.returncode != 0:
            raise ToolsError(f"échec de 'git submodule update' pour {owner}/{repo} : {update.stderr.strip()}")
    else:
        log(f"[{repo}] ajout comme sous-module ({url})...")
        add = _run_git(
            ["submodule", "add", "--depth", "1", "--force", url, local_dir],
            cwd=project_root,
            timeout=300,
        )
        if add.returncode != 0:
            raise ToolsError(f"échec de 'git submodule add' pour {owner}/{repo} : {add.stderr.strip()}")

    rev = _run_git(["rev-parse", "--short", "HEAD"], cwd=dest_dir)
    if rev.returncode != 0:
        raise ToolsError(f"impossible de lire le commit HEAD du sous-module {owner}/{repo} : {rev.stderr.strip()}")
    return rev.stdout.strip()


def _installed_version(dest_dir: Path) -> str | None:
    version_file = dest_dir / VERSION_MARKER_NAME
    if not version_file.is_file():
        return None
    try:
        return version_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _flatten_and_move(source_dir: Path, dest_dir: Path) -> None:
    """Déplace le contenu de `source_dir` vers `dest_dir` (créé si besoin,
    fichiers/dossiers existants de même nom écrasés). Si `source_dir` ne
    contient qu'un seul sous-dossier (archive GitHub ou Nexus emballée
    dans un dossier racine "NomOutil/"), c'est son contenu à lui qui est
    déplacé plutôt que ce dossier englobant lui-même."""
    top_level = list(source_dir.iterdir())
    content_dir = top_level[0] if len(top_level) == 1 and top_level[0].is_dir() else source_dir

    dest_dir.mkdir(parents=True, exist_ok=True)
    for item in content_dir.iterdir():
        target = dest_dir / item.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))


def _find_nexus_archive(tools_root: Path, mod_id: int) -> Path | None:
    """Cherche, directement à la racine de `tools_root` (Tools/), une
    archive téléchargée à la main depuis Nexus pour `mod_id` — les noms de
    fichiers du bouton "Manual Download" Nexus contiennent l'id du mod
    comme segment séparé par des tirets (ex:
    "Config App 1.1-5447-1-1-1706673565.zip" pour le mod 5447). Retourne
    la plus récente si plusieurs correspondent, ou None si aucune."""
    if not tools_root.is_dir():
        return None
    token = str(mod_id)
    candidates = [
        p
        for p in tools_root.iterdir()
        if p.is_file() and is_supported_archive(p) and token in re.split(r"[-_.]", p.stem)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _install_nexus_tool(
    entry: ToolEntry, project_root: Path, dest_dir: Path, *, log: LogFn
) -> None:
    """Installe un outil distribué uniquement via Nexus Mods (pas de
    dépôt GitHub, donc pas de release à récupérer par API). Le
    téléchargement direct via l'API Nexus nécessite un compte Premium
    (voir bg3_mod_tui/providers/nexus.py) : sans ça, on ne peut
    qu'attendre que l'utilisateur dépose l'archive lui-même, téléchargée
    via le lien "Manual Download" du site, à la racine de Tools/."""
    tools_root = project_root / NEXUS_TOOL_DOWNLOAD_DIR_NAME
    archive = _find_nexus_archive(tools_root, entry.nexus_mod_id)
    installed = _installed_version(dest_dir)

    if archive is None:
        if installed:
            log(f"[{entry.name}] déjà installé ({installed}).")
        else:
            log(
                f"[{entry.name}] pas de compte Nexus Premium : téléchargement "
                f"manuel requis. Va sur https://www.nexusmods.com/baldursgate3/mods/"
                f"{entry.nexus_mod_id} (bouton 'Manual Download') et dépose l'archive "
                f"téléchargée directement dans '{tools_root}/' — elle sera détectée et "
                "installée automatiquement à la prochaine MAJ des outils."
            )
        return

    version = archive.name
    if installed == version:
        log(f"[{entry.name}] déjà à jour ({version}).")
        archive.unlink()
        return

    log(f"[{entry.name}] archive détectée : {archive.name}, installation...")
    with tempfile.TemporaryDirectory(prefix="bg3modtools_tool_") as tmp:
        extract_dir = Path(tmp) / "extracted"
        try:
            extract_archive(archive, extract_dir)
        except ArchiveError as exc:
            log(f"[{entry.name}] échec d'extraction : {exc}")
            return
        _flatten_and_move(extract_dir, dest_dir)

    (dest_dir / VERSION_MARKER_NAME).write_text(version, encoding="utf-8")

    installed_archives_dir = tools_root / NEXUS_TOOL_ARCHIVE_SUBDIR
    installed_archives_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(archive), str(installed_archives_dir / archive.name))
    log(f"[{entry.name}] installé dans {dest_dir} ({version}).")


def _add_local_exclude(repo_dir: Path, *entries: str) -> None:
    """Ajoute `entries` à l'exclude local du dépôt git dans `repo_dir`
    (`.git/info/exclude`, jamais suivi ni poussé) plutôt qu'au `.gitignore`
    du dépôt — un fichier tiers suivi en amont par le sous-module, pas à
    nous de le modifier. Évite que nos ajouts locaux (marqueur de version,
    release précompilée) n'apparaissent comme non suivis dans `git status`.
    Idempotent (n'ajoute pas de doublon) ; sans effet si `repo_dir` n'est
    pas un dépôt git."""
    git_dir_res = _run_git(["rev-parse", "--git-dir"], cwd=repo_dir, timeout=10)
    if git_dir_res.returncode != 0:
        return
    git_dir = Path(git_dir_res.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_dir / git_dir
    exclude_path = git_dir / "info" / "exclude"
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_path.read_text(encoding="utf-8").splitlines() if exclude_path.is_file() else []
    to_add = [e for e in entries if e not in existing]
    if not to_add:
        return
    with exclude_path.open("a", encoding="utf-8") as fh:
        if existing and existing[-1] != "":
            fh.write("\n")
        for entry_line in to_add:
            fh.write(entry_line + "\n")


def _release_subdir_name(dest_dir: Path) -> str:
    """Nom du sous-dossier où déposer une release précompilée, choisi
    selon la convention de build du dépôt cloné dans `dest_dir` plutôt
    qu'un nom fixe imposé de notre côté : `release/` pour un projet Rust
    (miroir de `target/release/`, voir Cargo.toml), `dist/` pour un projet
    Python (miroir de la sortie de `python -m build`, voir
    pyproject.toml/setup.py/setup.cfg) — `dist/` par défaut sinon, la
    convention la plus répandue ailleurs (npm, etc.)."""
    if (dest_dir / "Cargo.toml").is_file():
        return "release"
    if any((dest_dir / f).is_file() for f in ("pyproject.toml", "setup.py", "setup.cfg")):
        return "dist"
    return "dist"


def _install_github_release(
    entry: ToolEntry, dest_dir: Path, release: ToolRelease, *, log: LogFn
) -> None:
    """Télécharge/extrait la release `release` dans un sous-dossier de
    `dest_dir` nommé selon `_release_subdir_name` (précompilé prêt à
    l'emploi), à côté du clone git de la source dans `dest_dir` lui-même."""
    subdir_name = _release_subdir_name(dest_dir)
    dist_dir = dest_dir / subdir_name
    installed = _installed_version(dist_dir)
    if installed == release.version:
        log(f"[{entry.name}] release déjà à jour ({release.version}).")
        return
    if installed:
        log(f"[{entry.name}] release : mise à jour {installed} -> {release.version}.")
    else:
        log(f"[{entry.name}] téléchargement de la release ({release.version})...")

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
            log(f"[{entry.name}] échec du téléchargement de la release : {exc}")
            return

        extract_dir = tmp_path / "extracted"
        try:
            extract_archive(archive_path, extract_dir)
        except ArchiveError as exc:
            log(f"[{entry.name}] échec d'extraction de la release : {exc}")
            return

        # Les archives GitHub (zipball / assets de release) contiennent
        # parfois un seul dossier racine ("repo-tag/") : on en prend le
        # contenu direct.
        _flatten_and_move(extract_dir, dist_dir)

        (dist_dir / VERSION_MARKER_NAME).write_text(release.version, encoding="utf-8")
        _add_local_exclude(dest_dir, f"/{subdir_name}/")
        log(f"[{entry.name}] release installée dans {dist_dir} ({release.version}).")


def download_and_extract_tool(
    entry: ToolEntry, project_root: Path, *, log: LogFn = lambda _m: None
) -> None:
    """Installe un outil GitHub dans `project_root/<entry.local_dir>` (ex:
    "Tools/xxx", tel que déclaré dans TOOLS.md) : la source est toujours
    déclarée/mise à jour comme sous-module git de BG3Tools lui-même (voir
    `_add_or_update_git_submodule`) directement dans ce dossier — un vrai
    sous-dépôt épinglé à un commit, pas une archive figée, pour pouvoir
    recompiler l'outil nous-mêmes au besoin — et si une release GitHub
    exploitable existe, elle est en plus téléchargée/extraite dans un
    sous-dossier nommé selon `_release_subdir_name` (précompilé prêt à
    l'emploi, sans repasser par une compilation locale à chaque MAJ).
    N'effectue aucun commit dans BG3Tools : voir
    `_add_or_update_git_submodule`. Pour un outil Nexus (pas de
    dépôt GitHub), voir `_install_nexus_tool` : le téléchargement direct
    n'est possible qu'avec un compte Nexus Premium, donc on attend une
    archive déposée à la main. Ignore silencieusement (avec message) les
    entrées sans dossier local ni dépôt GitHub ni mod Nexus identifiable
    (installation manuelle requise, ex: Native Mod Loader)."""
    if entry.local_dir is None:
        log(f"[{entry.name}] pas de dossier local défini, ignoré.")
        return

    dest_dir = project_root / entry.local_dir

    if entry.github_owner is None or entry.github_repo is None:
        if entry.nexus_mod_id is not None:
            _install_nexus_tool(entry, project_root, dest_dir, log=log)
        else:
            log(f"[{entry.name}] pas de dépôt GitHub, installation manuelle requise.")
        return

    try:
        version = _add_or_update_git_submodule(
            entry.github_owner, entry.github_repo, entry.local_dir, project_root, log=log
        )
    except ToolsError as exc:
        log(f"[{entry.name}] {exc}")
        return

    installed = _installed_version(dest_dir)
    if installed == version:
        log(f"[{entry.name}] source déjà à jour ({version}).")
    else:
        (dest_dir / VERSION_MARKER_NAME).write_text(version, encoding="utf-8")
        _add_local_exclude(dest_dir, f"/{VERSION_MARKER_NAME}")
        if installed:
            log(f"[{entry.name}] source mise à jour : {installed} -> {version}.")
        else:
            log(f"[{entry.name}] source clonée dans {dest_dir} ({version}).")

    try:
        release = _github_release(entry.github_owner, entry.github_repo)
    except ToolsError as exc:
        log(f"[{entry.name}] {exc}")
        return

    if release is not None:
        _install_github_release(entry, dest_dir, release, log=log)


def find_executables(tools_root: Path) -> list[Path]:
    """Liste les exécutables Windows (.exe) présents sous `tools_root`."""
    if not tools_root.is_dir():
        return []
    return sorted(tools_root.rglob("*.exe"))
