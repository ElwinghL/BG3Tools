"""Scénarios création/édition (single + batch) pour le benchmark .pak :
- bg3rustpaklib (seule lib des trois à savoir écrire) via le binaire natif
  `native_timing` (Tools/bg3rustpaklib/examples/native_timing.rs, release,
  sans Python/PyO3 dans la boucle — le binding PyO3 `pak_reader_rs` n'a
  jamais exposé l'écriture, donc il n'y a de toute façon pas de chemin
  "pipeline" à comparer pour bg3rustpaklib ici : seul un nombre "native"
  existe).
- Divine.exe (LSLib) via subprocess, `--action create-package`, en
  réutilisant le pattern d'invocation déjà utilisé en production dans
  `bg3_mod_tui/compat_framework.py`/`bg3_mod_tui/mod_fixer_fork.py`
  (Wine/Proton sous Linux) — mesuré tel quel ("pipeline", overhead
  Wine/Proton et lancement de process inclus, comme le reste du code le
  fait réellement), plus une mesure séparée de l'overhead de lancement pur
  (invocation triviale sans argument) pour pouvoir l'annoter/soustraire
  plutôt que le laisser polluer silencieusement le chiffre "opération".
- bg3pythonpaklib : lecture seule (cf. .claude/TODO.md §1f-1i) — aucun
  scénario création/édition ; les fonctions ci-dessous ne l'invoquent
  jamais et le rapport le documente comme N/A plutôt que de le passer sous
  silence.

"Édition" = extract + modifier un sous-ensemble de fichiers + recréer,
pour LES TROIS outils : aucun ne supporte l'édition incrémentale native
d'un .pak déjà écrit (cf. spec du benchmark) — ce n'est donc pas une
limitation propre à un seul outil, c'est acté comme tel.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from bg3_mod_tui.launcher import resolve_wine_bin
from bg3_mod_tui.platform_utils import find_proton_prefix, is_windows, to_wine_path
from scripts.pak_bench import strings
from scripts.pak_bench.common import ScenarioResult

_BG3RUSTPAKLIB_DIR = Path(__file__).resolve().parent.parent.parent / "Tools" / "bg3rustpaklib"
NATIVE_TIMING_BIN = _BG3RUSTPAKLIB_DIR / "target" / "release" / "examples" / "native_timing"


class NativeTimingMissing(RuntimeError):
    pass


def _require_native_timing() -> None:
    if not NATIVE_TIMING_BIN.is_file():
        raise NativeTimingMissing(
            strings.NATIVE_TIMING_MISSING.format(
                name=NATIVE_TIMING_BIN.name, path=NATIVE_TIMING_BIN
            )
        )


def _run_native_timing(args: list[str], *, timeout: float = 600) -> dict[str, Any]:
    _require_native_timing()
    proc = subprocess.run(
        [str(NATIVE_TIMING_BIN), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    stdout = proc.stdout.strip()
    line = stdout.splitlines()[-1] if stdout else ""
    if not line:
        return {
            "error": strings.NATIVE_TIMING_NO_JSON.format(
                code=proc.returncode, stderr=proc.stderr.strip()[:500]
            )
        }
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        return {"error": strings.NATIVE_TIMING_BAD_JSON.format(exc=exc)}


# --------------------------------------------------------------------------
# bg3rustpaklib (natif, seul chemin mesurable — cf. docstring module)
# --------------------------------------------------------------------------


def rust_create_single(
    source_dir: Path, output_pak: Path, *, version: str = "v18"
) -> ScenarioResult:
    result = ScenarioResult(tool="bg3rustpaklib", scenario="create-single", label=output_pak.name)
    payload = _run_native_timing(["create", str(source_dir), str(output_pak), version])
    if "error" in payload:
        result.error = payload["error"]
        return result
    result.seconds = {"build": payload["build_seconds"], "verify": payload["verify_seconds"]}
    result.total_seconds = payload["build_seconds"] + payload["verify_seconds"]
    result.verify_ok = payload.get("verify_ok")
    result.file_count = payload.get("file_count", 0)
    return result


def rust_create_batch(
    pairs: list[tuple[Path, Path]], *, version: str = "v18"
) -> list[ScenarioResult]:
    """`pairs` : [(source_dir, output_pak), ...] — un seul lancement de
    `native_timing`, donc le coût de démarrage du process n'est payé
    qu'une fois pour tout le lot (comparable au mode batch Divine.exe côté
    lecture)."""
    args = ["batch-create", version] + [f"{src}:{dst}" for src, dst in pairs]
    proc_start = time.monotonic()
    payload = _run_native_timing(args, timeout=max(600, 10 * len(pairs)))
    batch_wall_seconds = time.monotonic() - proc_start
    results: list[ScenarioResult] = []
    if isinstance(payload, dict) and "error" in payload:
        for _src, dst in pairs:
            r = ScenarioResult(tool="bg3rustpaklib", scenario="create-batch", label=dst.name)
            r.error = payload["error"]
            results.append(r)
        return results
    entries = payload if isinstance(payload, list) else []
    for entry in entries:
        r = ScenarioResult(
            tool="bg3rustpaklib", scenario="create-batch", label=Path(entry["output"]).name
        )
        inner = entry.get("result", {})
        if "error" in inner:
            r.error = inner["error"]
        else:
            r.seconds = {"build": inner["build_seconds"], "verify": inner["verify_seconds"]}
            r.total_seconds = inner["build_seconds"] + inner["verify_seconds"]
            r.verify_ok = inner.get("verify_ok")
            r.file_count = inner.get("file_count", 0)
        results.append(r)
    if results:
        results[0].seconds["batch_wall_total"] = batch_wall_seconds
    return results


def rust_edit_single(
    input_pak: Path, overlay_dir: Path, output_pak: Path, *, version: str = "v18"
) -> ScenarioResult:
    result = ScenarioResult(tool="bg3rustpaklib", scenario="edit-single", label=output_pak.name)
    payload = _run_native_timing(
        ["edit", str(input_pak), str(overlay_dir), str(output_pak), version]
    )
    if "error" in payload:
        result.error = payload["error"]
        return result
    result.seconds = {
        "extract": payload["extract_seconds"],
        "modify": payload["modify_seconds"],
        "repack": payload["repack_seconds"],
        "verify": payload["verify_seconds"],
    }
    result.total_seconds = sum(result.seconds.values())
    result.verify_ok = payload.get("verify_ok")
    result.file_count = payload.get("file_count", 0)
    return result


def rust_edit_batch(
    triples: list[tuple[Path, Path, Path]], *, version: str = "v18"
) -> list[ScenarioResult]:
    """`triples` : [(input_pak, overlay_dir, output_pak), ...]."""
    args = ["batch-edit", version] + [f"{i}:{o}:{d}" for i, o, d in triples]
    proc_start = time.monotonic()
    payload = _run_native_timing(args, timeout=max(600, 15 * len(triples)))
    batch_wall_seconds = time.monotonic() - proc_start
    results: list[ScenarioResult] = []
    if isinstance(payload, dict) and "error" in payload:
        for _i, _o, dst in triples:
            r = ScenarioResult(tool="bg3rustpaklib", scenario="edit-batch", label=dst.name)
            r.error = payload["error"]
            results.append(r)
        return results
    entries = payload if isinstance(payload, list) else []
    for entry in entries:
        r = ScenarioResult(
            tool="bg3rustpaklib", scenario="edit-batch", label=Path(entry["output"]).name
        )
        inner = entry.get("result", {})
        if "error" in inner:
            r.error = inner["error"]
        else:
            r.seconds = {
                "extract": inner["extract_seconds"],
                "modify": inner["modify_seconds"],
                "repack": inner["repack_seconds"],
                "verify": inner["verify_seconds"],
            }
            r.total_seconds = sum(r.seconds.values())
            r.verify_ok = inner.get("verify_ok")
            r.file_count = inner.get("file_count", 0)
        results.append(r)
    if results:
        results[0].seconds["batch_wall_total"] = batch_wall_seconds
    return results


# --------------------------------------------------------------------------
# Divine.exe (pipeline réel : subprocess + Wine/Proton sous Linux)
# --------------------------------------------------------------------------


def _divine_command(
    divine_exe: Path, reference_path: Path, args_tail: list[str]
) -> tuple[list[str], dict | None]:
    env = None
    if is_windows():
        return [str(divine_exe), *args_tail], env
    prefix = find_proton_prefix(reference_path)
    if prefix is None:
        raise RuntimeError("Impossible de déterminer le préfixe Proton de BG3.")
    wine_bin = resolve_wine_bin(prefix)
    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix)
    return [wine_bin, str(divine_exe)], env


def divine_launch_overhead_seconds(divine_exe: Path, reference_path: Path) -> float | None:
    """Invocation triviale (pas d'argument valide -> Divine.exe affiche son
    aide et quitte) pour isoler le coût de lancement pur du process
    (Wine/CLR sous Linux) de celui d'une vraie opération — cf. demande de
    mesurer "dans son jus" plutôt que de laisser cet overhead polluer
    silencieusement les chiffres d'opération. Retourne None si le
    lancement échoue (pas bloquant : juste pas de baseline)."""
    try:
        command, env = _divine_command(divine_exe, reference_path, [])
    except RuntimeError:
        return None
    start = time.monotonic()
    try:
        subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return time.monotonic() - start


def _to_wine_path_or_str(path: Path, *, use_wine_path: bool) -> str:
    return to_wine_path(path) if use_wine_path else str(path)


def divine_create_single(
    source_dir: Path, output_pak: Path, *, divine_exe: Path, reference_path: Path
) -> ScenarioResult:
    result = ScenarioResult(tool="Divine.exe", scenario="create-single", label=output_pak.name)
    use_wine_path = not is_windows()
    args_tail = [
        "-g",
        "bg3",
        "-a",
        "create-package",
        "-s",
        _to_wine_path_or_str(source_dir, use_wine_path=use_wine_path),
        "-d",
        _to_wine_path_or_str(output_pak, use_wine_path=use_wine_path),
    ]
    try:
        command, env = _divine_command(divine_exe, reference_path, args_tail)
    except RuntimeError as exc:
        result.error = str(exc)
        return result
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=180,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        result.error = str(exc)
        return result
    result.total_seconds = time.monotonic() - start
    result.seconds = {"create_pipeline": result.total_seconds}
    if proc.returncode != 0 or not output_pak.is_file():
        result.error = (proc.stderr.strip() or proc.stdout.strip() or f"code {proc.returncode}")[
            :500
        ]
        return result
    result.verify_ok = True
    return result


def divine_create_batch(
    pairs: list[tuple[Path, Path]], *, divine_exe: Path, reference_path: Path
) -> list[ScenarioResult]:
    """Divine.exe n'a pas d'action batch native pour `create-package`
    (contrairement à `extract-packages` côté lecture) — un lancement de
    process par dossier source est donc la seule option ; le "batch" ici
    mesure simplement le total encouru par le lot au lieu de tenter une
    amortisation qui n'existe pas côté outil (documenté tel quel dans le
    rapport plutôt que présenté comme équivalent au mode batch lecture)."""
    return [
        divine_create_single(src, dst, divine_exe=divine_exe, reference_path=reference_path)
        for src, dst in pairs
    ]


def divine_edit_single(
    input_pak: Path,
    overlay_dir: Path,
    output_pak: Path,
    *,
    divine_exe: Path,
    reference_path: Path,
    work_dir: Path,
) -> ScenarioResult:
    result = ScenarioResult(tool="Divine.exe", scenario="edit-single", label=output_pak.name)
    use_wine_path = not is_windows()
    extract_dir = work_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        command, env = _divine_command(
            divine_exe,
            reference_path,
            [
                "-g",
                "bg3",
                "-a",
                "extract-package",
                "-s",
                _to_wine_path_or_str(input_pak, use_wine_path=use_wine_path),
                "-d",
                _to_wine_path_or_str(extract_dir, use_wine_path=use_wine_path),
            ],
        )
    except RuntimeError as exc:
        result.error = str(exc)
        return result

    extract_start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=180,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        result.error = str(exc)
        return result
    extract_seconds = time.monotonic() - extract_start
    if proc.returncode != 0:
        result.error = (proc.stderr.strip() or proc.stdout.strip() or f"code {proc.returncode}")[
            :500
        ]
        return result

    modify_start = time.monotonic()
    modified_files = 0
    if overlay_dir.is_dir():
        for src in overlay_dir.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(overlay_dir)
            dest = extract_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(src.read_bytes())
            modified_files += 1
    modify_seconds = time.monotonic() - modify_start

    repack_result = divine_create_single(
        extract_dir, output_pak, divine_exe=divine_exe, reference_path=reference_path
    )

    result.seconds = {
        "extract": extract_seconds,
        "modify": modify_seconds,
        "repack": repack_result.total_seconds,
    }
    result.total_seconds = extract_seconds + modify_seconds + repack_result.total_seconds
    result.verify_ok = repack_result.verify_ok
    result.error = repack_result.error
    result.file_count = modified_files
    return result
