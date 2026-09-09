"""Construction du .pak de BG3 Compatibility Framework depuis ses sources
GitHub, via Divine.exe (LSLib, voir Tools/ExportTools/) : ce mod n'a ni
release GitHub avec un .pak tout fait (assets vides), ni de .pak commité
dans son dépôt (juste les sources, structure LSLib classique — un dossier
`Mods/<NomDuMod>/` à empaqueter) — contrairement à un mod Nexus/mod.io
classique, on doit donc le compiler nous-mêmes après l'avoir téléchargé
comme un outil (voir TOOLS.md et tools_manager.py)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from bg3_mod_tui.launcher import resolve_wine_bin
from bg3_mod_tui.platform_utils import find_proton_prefix, is_windows

LogFn = Callable[[str], None]

TOOL_LOCAL_DIR_NAME = "BG3-Compatibility-Framework"
_SOURCE_SUBDIR = "CompatibilityFramework"
PAK_NAME = "CompatibilityFramework.pak"


class CompatibilityFrameworkError(RuntimeError):
    pass


def find_divine_exe(tools_dir: Path) -> Path | None:
    """Cherche Divine.exe (LSLib) sous `tools_dir` — son chemin exact
    dépend de l'archive de release (ex: ExportTools/Packed/Tools/)."""
    matches = list(tools_dir.rglob("Divine.exe"))
    return matches[0] if matches else None


def find_source_root(tools_dir: Path) -> Path | None:
    """Racine à passer à Divine.exe (`--source`) : le dossier contenant
    `Mods/` (et `Public/` s'il existe) du dépôt téléchargé — c'est ce
    dossier, pas le sous-dossier de mod lui-même, qui correspond à la
    racine attendue à l'intérieur du .pak."""
    root = tools_dir / TOOL_LOCAL_DIR_NAME / _SOURCE_SUBDIR
    return root if (root / "Mods").is_dir() else None


def build_pak(
    tools_dir: Path,
    mods_dir: Path,
    *,
    reference_path: Path,
    log: LogFn = lambda _msg: None,
) -> Path:
    """Construit `CompatibilityFramework.pak` depuis les sources
    téléchargées et le dépose dans `mods_dir`. Lève
    `CompatibilityFrameworkError` si les sources ou Divine.exe sont
    introuvables (télécharger l'outil au préalable via "MAJ des outils"),
    ou si l'empaquetage échoue."""
    source_root = find_source_root(tools_dir)
    if source_root is None:
        raise CompatibilityFrameworkError(
            f"Sources introuvables (Tools/{TOOL_LOCAL_DIR_NAME}/{_SOURCE_SUBDIR}/Mods/) "
            "— télécharge d'abord l'outil via « MAJ des outils »."
        )
    divine_exe = find_divine_exe(tools_dir)
    if divine_exe is None:
        raise CompatibilityFrameworkError(
            "Divine.exe introuvable sous Tools/ExportTools/ — télécharge d'abord "
            "LSLib via « MAJ des outils »."
        )

    mods_dir.mkdir(parents=True, exist_ok=True)
    dest_pak = mods_dir / PAK_NAME

    args_tail = [
        "--game", "bg3",
        "--action", "create-package",
        "--source", str(source_root),
        "--destination", str(dest_pak),
    ]

    env = None
    if is_windows():
        command = [str(divine_exe), *args_tail]
    else:
        prefix = find_proton_prefix(reference_path)
        if prefix is None:
            raise CompatibilityFrameworkError("Impossible de déterminer le préfixe Proton de BG3.")
        wine_bin = resolve_wine_bin(prefix)
        env = os.environ.copy()
        env["WINEPREFIX"] = str(prefix)
        command = [wine_bin, str(divine_exe), *args_tail]

    log(f"Empaquetage de {PAK_NAME} via Divine.exe...")
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise CompatibilityFrameworkError("Timeout lors de l'empaquetage via Divine.exe.") from exc
    except OSError as exc:
        raise CompatibilityFrameworkError(f"Échec du lancement de Divine.exe : {exc}") from exc

    if result.returncode != 0 or not dest_pak.is_file():
        detail = result.stderr.strip() or result.stdout.strip() or f"code {result.returncode}"
        raise CompatibilityFrameworkError(f"Échec de l'empaquetage : {detail}")

    log(f"{PAK_NAME} créé -> {dest_pak}")
    return dest_pak
