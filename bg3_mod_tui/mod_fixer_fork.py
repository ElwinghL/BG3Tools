"""Fork local de Mod Fixer (Nexus #141, Norbyte) avec un meta.lsx propre.

Mod Fixer n'est pas un mod comme les autres : il ne définit aucun module à
lui — son seul contenu est un fichier vide,
`Mods/Gustav/Story/RawFiles/Goals/ForceRecompile.txt`, déposé directement
dans le dossier du module de BASE du jeu (Gustav) pour forcer la
recompilation de sa story Osiris (corrige des soucis de compat après
ajout/retrait de mods). N'ayant jamais eu besoin d'un `meta.lsx`/UUID, la
validation "Load Order" de BG3 Mod Manager le signale (Medium) — bénin,
mais gênant à distinguer d'un vrai problème.

Ce module reconstruit donc un module séparé ("ModFixerFork", meta.lsx
propre avec un UUID généré) contenant le même fichier au même chemin
relatif — sous son propre dossier, jamais sous `Mods/Gustav/` (écraser le
meta.lsx du module de base serait dangereux). Effet non garanti à 100% :
si le moteur cible spécifiquement le cache du module Gustav pour décider
de recompiler la story, ce fork sous un autre nom de module pourrait ne
pas avoir le même effet — Nexus indique de toute façon que ce mod n'est
plus nécessaire à partir du Patch 7 de BG3.

Comme pour `compat_framework.py`, le .pak résultant n'est jamais committé
(voir .gitignore) : reconstruit localement via Divine.exe (LSLib) à partir
du ModFixer.pak déjà déployé par l'utilisateur."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from bg3_mod_tui.compat_framework import find_divine_exe
from bg3_mod_tui.launcher import resolve_wine_bin
from bg3_mod_tui.platform_utils import find_proton_prefix, is_windows, to_wine_path

LogFn = Callable[[str], None]

ORIGINAL_PAK_NAME = "ModFixer.pak"
FORK_PAK_NAME = "ModFixerFork.pak"
FORK_MODULE_NAME = "ModFixerFork"
# Chemin du fichier "déclencheur" à l'intérieur du module d'origine
# (Gustav) — reproduit tel quel sous le nouveau module.
_OVERRIDE_RELATIVE_PATH = Path("Story/RawFiles/Goals/ForceRecompile.txt")
_ORIGINAL_MODULE_NAME = "Gustav"

_DIVINE_TIMEOUT_SECONDS = 60

_META_LSX_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<save>
  <version major="4" minor="0" revision="0" build="49" />
  <region id="Config">
    <node id="root">
      <children>
        <node id="ModuleInfo">
          <attribute id="Author" type="LSWString" value="Norbyte (Mod Fixer) -- meta.lsx ajoute par ModTools" />
          <attribute id="CharacterCreationLevelName" type="FixedString" value="" />
          <attribute id="Description" type="LSWString" value="Fork local de Mod Fixer (Nexus #141) avec un meta.lsx propre, genere par ModTools (bg3_mod_tui/mod_fixer_fork.py) pour ne plus etre signale comme sans metadonnees par les validateurs de load order." />
          <attribute id="Folder" type="LSWString" value="{folder}" />
          <attribute id="GMTemplate" type="FixedString" value="" />
          <attribute id="LobbyLevelName" type="FixedString" value="" />
          <attribute id="MD5" type="LSString" value="" />
          <attribute id="MainMenuBackgroundVideo" type="FixedString" value="" />
          <attribute id="MenuLevelName" type="FixedString" value="" />
          <attribute id="Name" type="FixedString" value="{folder}" />
          <attribute id="NumPlayers" type="uint8" value="4" />
          <attribute id="PhotoBooth" type="FixedString" value="" />
          <attribute id="StartupLevelName" type="FixedString" value="" />
          <attribute id="Tags" type="LSWString" value="" />
          <attribute id="Type" type="FixedString" value="Patch" />
          <attribute id="UUID" type="FixedString" value="{uuid}" />
          <attribute id="Version64" type="int64" value="1" />
          <children>
            <node id="PublishVersion">
              <attribute id="Version64" type="int64" value="1" />
            </node>
            <node id="Scripts" />
            <node id="TargetModes">
              <children>
                <node id="Target">
                  <attribute id="Object" type="FixedString" value="Story" />
                </node>
              </children>
            </node>
          </children>
        </node>
      </children>
    </node>
  </region>
</save>
"""


class ModFixerForkError(RuntimeError):
    pass


def _divine_command(
    divine_exe: Path, action: str, extra_args: list[str], *, reference_path: Path
) -> tuple[list[str], dict[str, str] | None]:
    """Construit la commande Divine.exe (+ environnement Wine si besoin),
    identique dans son principe à `pak_metadata._run_divine`/
    `compat_framework.build_pak` : sous Linux, Divine.exe (.NET) valide ses
    chemins via `System.Uri` et rejette un chemin Unix brut, d'où la
    conversion en chemin Windows (`to_wine_path`) pour tout argument de
    chemin passé dans `extra_args`."""
    if is_windows():
        return [str(divine_exe), "-g", "bg3", "-a", action, *extra_args], None

    prefix = find_proton_prefix(reference_path)
    if prefix is None:
        raise ModFixerForkError("Impossible de déterminer le préfixe Proton de BG3.")
    wine_bin = resolve_wine_bin(prefix)
    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    return [wine_bin, str(divine_exe), "-g", "bg3", "-a", action, *extra_args], env


def _run_divine(
    divine_exe: Path, action: str, extra_args: list[str], *, reference_path: Path
) -> None:
    command, env = _divine_command(divine_exe, action, extra_args, reference_path=reference_path)
    try:
        result = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=_DIVINE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ModFixerForkError(f"Timeout Divine.exe ({action}) : {exc}") from exc
    except OSError as exc:
        raise ModFixerForkError(f"Échec du lancement de Divine.exe : {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"code {result.returncode}"
        raise ModFixerForkError(f"Échec Divine.exe ({action}) : {detail}")


def build_fork(
    mods_dir: Path,
    tools_dir: Path,
    *,
    reference_path: Path,
    log: LogFn = lambda _msg: None,
) -> Path:
    """Reconstruit `ModFixerFork.pak` (voir docstring du module) dans
    `mods_dir`, à partir de `mods_dir/ModFixer.pak` déjà déployé.

    Lève `ModFixerForkError` si `ModFixer.pak` ou Divine.exe sont
    introuvables, ou si son contenu ne correspond pas à celui attendu
    (mod mis à jour entre-temps par son auteur, ou fichier différent) —
    on refuse de repackager à l'aveugle plutôt que de produire un fork
    silencieusement incorrect."""
    original_pak = mods_dir / ORIGINAL_PAK_NAME
    if not original_pak.is_file():
        raise ModFixerForkError(
            f"{ORIGINAL_PAK_NAME} introuvable dans {mods_dir} — installe d'abord Mod "
            "Fixer (Nexus #141) normalement avant de le forker."
        )
    divine_exe = find_divine_exe(tools_dir)
    if divine_exe is None:
        raise ModFixerForkError(
            "Divine.exe introuvable sous Tools/ExportTools/ — télécharge d'abord "
            "LSLib via « MAJ des outils »."
        )

    use_wine_path = not is_windows()

    with tempfile.TemporaryDirectory(prefix="bg3modtools_modfixerfork_") as tmp:
        tmp_path = Path(tmp)
        extract_dir = tmp_path / "extracted"

        log(f"Extraction de {ORIGINAL_PAK_NAME} via Divine.exe...")
        _run_divine(
            divine_exe,
            "extract-package",
            [
                "-s", to_wine_path(original_pak) if use_wine_path else str(original_pak),
                "-d", to_wine_path(extract_dir) if use_wine_path else str(extract_dir),
            ],
            reference_path=reference_path,
        )

        source_file = extract_dir / "Mods" / _ORIGINAL_MODULE_NAME / _OVERRIDE_RELATIVE_PATH
        if not source_file.is_file():
            raise ModFixerForkError(
                f"Contenu inattendu dans {ORIGINAL_PAK_NAME} (fichier "
                f"'{_OVERRIDE_RELATIVE_PATH}' introuvable sous "
                f"Mods/{_ORIGINAL_MODULE_NAME}/) — le mod a peut-être changé depuis, "
                "refus de repackager à l'aveugle."
            )

        fork_module_dir = tmp_path / "fork_source" / "Mods" / FORK_MODULE_NAME
        dest_override = fork_module_dir / _OVERRIDE_RELATIVE_PATH
        dest_override.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, dest_override)

        new_uuid = str(uuid.uuid4())
        (fork_module_dir / "meta.lsx").write_text(
            _META_LSX_TEMPLATE.format(folder=FORK_MODULE_NAME, uuid=new_uuid),
            encoding="utf-8",
        )

        dest_pak = mods_dir / FORK_PAK_NAME
        log(f"Empaquetage de {FORK_PAK_NAME} (UUID {new_uuid}) via Divine.exe...")
        _run_divine(
            divine_exe,
            "create-package",
            [
                "-s", to_wine_path(fork_module_dir.parent.parent) if use_wine_path else str(fork_module_dir.parent.parent),
                "-d", to_wine_path(dest_pak) if use_wine_path else str(dest_pak),
            ],
            reference_path=reference_path,
        )

    if not dest_pak.is_file():
        raise ModFixerForkError(f"Échec de l'empaquetage : {dest_pak} n'a pas été créé.")

    log(
        f"{FORK_PAK_NAME} créé -> {dest_pak}. {ORIGINAL_PAK_NAME} n'a pas été "
        "touché/supprimé — à retirer toi-même de Mods/ si tu ne gardes que le fork."
    )
    return dest_pak
