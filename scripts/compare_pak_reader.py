#!/usr/bin/env python3
"""Compare quatre lecteurs de .pak BG3 (LSPK) — Python natif (`pak_reader`),
Rust via binding PyO3 (`pak_reader_rs`, crate `bg3rustpaklib` + PyO3),
Rust natif isolé (binaire `native_timing`, mêmes opérations mais sans
Python/PyO3 dans la boucle) et Divine.exe — chacun exécuté séparément avec
son propre rapport JSON, puis un diff final qui les croise (identité
UUID/Name, liste des fichiers, tailles, hash SHA-256 du contenu
décompressé).

Le chemin `rust-native` existe spécifiquement pour isoler le coût du
binding FFI/PyO3 : `rust` (PyO3) mesure Python → PyO3 → `bg3rustpaklib`,
`rust-native` mesure `bg3rustpaklib` directement en Rust pur. La différence
entre les deux quantifie l'overhead FFI/binding (voir
`Tools/bg3rustpaklib/README.md#comparisons`). Comme ce chemin ne remonte
pas la table des fichiers ni les hash de contenu (timing seulement), il
n'est pas croisé structurellement dans `diff` — seule sa comparaison de
timing avec `rust` y est affichée.

Deux étapes :

1. `run --tool {python,rust,rust-native,divine}` : scanne des .pak, produit
   `reports/<tool>_report.json` (chronométrage inclus). Un run par outil,
   indépendant des autres — on peut relancer un seul outil sans repasser
   sur les autres.
2. `diff` : charge les rapports présents sous `reports/`, croise tout ce
   qui est commun entre outils (identité, table des fichiers, tailles,
   hash de contenu) et affiche les divergences + un résumé.

Usage :
    python scripts/compare_pak_reader.py run --tool python
    python scripts/compare_pak_reader.py run --tool rust
    python scripts/compare_pak_reader.py run --tool rust-native
    python scripts/compare_pak_reader.py run --tool divine --divine-exe Tools/ExportTools/Tools/Divine.exe
    python scripts/compare_pak_reader.py diff

Le lecteur Rust (binding PyO3) doit être compilé au préalable :
    uv run maturin develop --manifest-path rust/pak_reader_rs/Cargo.toml

Le binaire Rust natif (`rust-native`) doit être compilé au préalable :
    cargo build --example native_timing --release --manifest-path Tools/bg3rustpaklib/Cargo.toml
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bg3_mod_tui.compat_framework import find_divine_exe
from bg3_mod_tui.config import load_config
from bg3_mod_tui.pak_metadata import PakMetadataError, _path_arg, _run_divine, parse_meta_lsx
from bg3_mod_tui.platform_utils import is_windows
from scripts.pak_bench.common import (
    REPORTS_DIR,
    PakRecord,
    _pick_sample_names,
    _sha256,
    _write_report,
)

_BG3RUSTPAKLIB_DIR = Path(__file__).resolve().parent.parent / "Tools" / "bg3rustpaklib"
_NATIVE_TIMING_BIN = _BG3RUSTPAKLIB_DIR / "target" / "release" / "examples" / "native_timing"
_COMPRESSION_NAMES = {0: "aucune", 1: "zlib", 2: "lz4", 3: "zstd"}


# --------------------------------------------------------------------------
# Voie Python native (bg3_mod_tui.pak_reader)
# --------------------------------------------------------------------------


def _run_python(
    pak_paths: list[Path],
    sample_cap: int,
    *,
    records: dict[str, PakRecord] | None = None,
    on_progress: Callable[[PakRecord], None] | None = None,
) -> dict[str, PakRecord]:
    from bg3_mod_tui.pak_reader import PakArchive, PakReaderError, parse_meta_lsx_bytes

    if records is None:
        records = {}
    for pak_path in pak_paths:
        record = PakRecord(file=pak_path.name)
        records[pak_path.name] = record
        start = time.monotonic()
        try:
            archive = PakArchive.open(pak_path)
        except PakReaderError as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            if on_progress is not None:
                on_progress(record)
            continue
        record.index_or_extract_seconds = time.monotonic() - start
        record.entries = {
            e.name.replace("\\", "/"): {
                "size": e.uncompressed_size,
                "compression": e.compression_method,
            }
            for e in archive.entries
        }
        meta_entry = archive.find_suffix("meta.lsx")
        if meta_entry is not None:
            identity = parse_meta_lsx_bytes(archive.read(meta_entry))
            if identity is not None:
                record.identity = (identity[0], identity[1])

        start = time.monotonic()
        for name in _pick_sample_names(record.entries, sample_cap):
            entry = archive.find(name)
            if entry is None:
                continue
            try:
                record.content_hashes[name] = _sha256(archive.read(entry))
            except Exception as exc:  # noqa: BLE001 - une entrée en erreur ne doit pas interrompre le run
                record.content_errors[name] = f"{type(exc).__name__}: {exc}"
        record.content_seconds = time.monotonic() - start
        archive.close()
        if on_progress is not None:
            on_progress(record)
    return records


# --------------------------------------------------------------------------
# Voie Rust native (pak_reader_rs)
# --------------------------------------------------------------------------


def _run_rust(
    pak_paths: list[Path],
    sample_cap: int,
    *,
    records: dict[str, PakRecord] | None = None,
    on_progress: Callable[[PakRecord], None] | None = None,
) -> dict[str, PakRecord]:
    try:
        import pak_reader_rs as r
    except ImportError as exc:
        raise SystemExit(
            "Module 'pak_reader_rs' introuvable — compile-le d'abord :\n"
            "  uv run maturin develop --manifest-path rust/pak_reader_rs/Cargo.toml"
        ) from exc

    if records is None:
        records = {}
    for pak_path in pak_paths:
        record = PakRecord(file=pak_path.name)
        records[pak_path.name] = record
        start = time.monotonic()
        try:
            archive = r.PakArchive.open(str(pak_path))
        except r.PakReaderError as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            if on_progress is not None:
                on_progress(record)
            continue
        record.index_or_extract_seconds = time.monotonic() - start
        record.entries = {
            e.name: {"size": e.uncompressed_size, "compression": e.compression_method}
            for e in archive.entries()
        }
        meta_entry = archive.find_suffix("meta.lsx")
        if meta_entry is not None:
            identity = r.parse_meta_lsx_bytes(bytes(archive.read(meta_entry)))
            if identity is not None:
                record.identity = (identity[0], identity[1])

        start = time.monotonic()
        for name in _pick_sample_names(record.entries, sample_cap):
            entry = archive.find(name)
            if entry is None:
                continue
            try:
                record.content_hashes[name] = _sha256(bytes(archive.read(entry)))
            except Exception as exc:  # noqa: BLE001 - une entrée en erreur ne doit pas interrompre le run
                record.content_errors[name] = f"{type(exc).__name__}: {exc}"
        record.content_seconds = time.monotonic() - start
        if on_progress is not None:
            on_progress(record)
    return records


# --------------------------------------------------------------------------
# Voie Rust natif isolé (pas de Python/PyO3 dans la boucle)
# --------------------------------------------------------------------------


def _run_rust_native(
    pak_paths: list[Path],
    sample_cap: int,
    *,
    records: dict[str, PakRecord] | None = None,
    on_progress: Callable[[PakRecord], None] | None = None,
) -> dict[str, PakRecord]:
    """Invoque le binaire autonome `native_timing` (crate `bg3rustpaklib`,
    voir `Tools/bg3rustpaklib/examples/native_timing.rs`) en sous-processus,
    un lancement par `.pak`, et parse sa sortie JSON (une ligne). Ce chemin
    ne remonte ni la table des fichiers ni les hash de contenu (le binaire
    ne les imprime pas — seulement le timing) : `record.entries` et
    `record.content_hashes` restent vides, donc ce rapport n'est pas croisé
    structurellement par `cmd_diff` (seule sa comparaison de temps avec
    `rust` y apparaît). But précis : isoler le coût de la lecture/
    décompression Rust pure de celui du binding FFI/PyO3 mesuré par
    `_run_rust`."""
    if not _NATIVE_TIMING_BIN.is_file():
        raise SystemExit(
            f"Binaire '{_NATIVE_TIMING_BIN.name}' introuvable ({_NATIVE_TIMING_BIN}) — compile-le d'abord :\n"
            "  cargo build --example native_timing --release "
            "--manifest-path Tools/bg3rustpaklib/Cargo.toml"
        )

    if records is None:
        records = {}
    for pak_path in pak_paths:
        record = PakRecord(file=pak_path.name)
        records[pak_path.name] = record
        try:
            proc = subprocess.run(
                [str(_NATIVE_TIMING_BIN), "--sample", str(sample_cap), str(pak_path)],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except OSError as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            if on_progress is not None:
                on_progress(record)
            continue

        stdout = proc.stdout.strip()
        line = stdout.splitlines()[-1] if stdout else ""
        if not line:
            record.error = (
                f"pas de sortie JSON (code {proc.returncode}) : {proc.stderr.strip()[:500]}"
            )
            if on_progress is not None:
                on_progress(record)
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            record.error = f"JSON invalide depuis native_timing : {exc}"
            if on_progress is not None:
                on_progress(record)
            continue

        if payload.get("error"):
            record.error = str(payload["error"])
        else:
            record.index_or_extract_seconds = float(payload.get("index_seconds", 0.0))
            record.content_seconds = float(payload.get("content_seconds", 0.0))
        if on_progress is not None:
            on_progress(record)
    return records


# --------------------------------------------------------------------------
# Voie Divine.exe (référence)
# --------------------------------------------------------------------------


def _finalize_divine_extraction(
    record: PakRecord, work_dir: Path, sample_cap: int, *, reference_path: Path
) -> None:
    """Remplit `record` (entries/identity/content_hashes) à partir des
    fichiers déjà extraits par Divine.exe dans `work_dir` — partagé entre
    le mode per-file et le mode batch, qui ne diffèrent que dans la façon
    dont l'extraction elle-même est chronométrée/lancée. `reference_path`
    n'est plus utilisé ici (gardé pour signature symétrique avec l'appelant)
    mais aucune écriture n'a lieu : uniquement des lectures dans `work_dir`
    (jamais dans le `.pak` source lui-même)."""
    disk_files = {
        str(p.relative_to(work_dir)).replace("\\", "/"): p
        for p in work_dir.rglob("*")
        if p.is_file()
    }
    record.entries = {
        name: {"size": p.stat().st_size, "compression": -1} for name, p in disk_files.items()
    }

    from bg3_mod_tui.pak_reader import extract_uuid_from_lsf_bytes

    lsx_matches = [n for n in disk_files if n.lower().endswith("meta.lsx")]
    if lsx_matches:
        identity = parse_meta_lsx(disk_files[lsx_matches[0]])
        if identity is not None:
            record.identity = identity
    else:
        lsf_matches = [n for n in disk_files if n.lower().endswith("meta.lsf")]
        if lsf_matches:
            uuid = extract_uuid_from_lsf_bytes(disk_files[lsf_matches[0]].read_bytes())
            if uuid:
                record.identity = (uuid, "")

    start = time.monotonic()
    for name in _pick_sample_names(record.entries, sample_cap):
        try:
            record.content_hashes[name] = _sha256(disk_files[name].read_bytes())
        except Exception as exc:  # noqa: BLE001 - une entrée en erreur ne doit pas interrompre le run
            record.content_errors[name] = f"{type(exc).__name__}: {exc}"
    record.content_seconds = time.monotonic() - start


def _run_divine_batch_tool(
    pak_paths: list[Path],
    scan_dir: Path,
    sample_cap: int,
    *,
    divine_exe: Path,
    reference_path: Path,
    records: dict[str, PakRecord] | None = None,
    on_progress: Callable[[PakRecord], None] | None = None,
) -> tuple[dict[str, PakRecord], float]:
    """Équivalent de `_run_divine_tool`, mais via l'action native
    `extract-packages` de LSLib (voir `Divine/CLI/CommandLinePackageProcessor.
    BatchExtract` dans `Tools/ExportTools`) : un seul lancement de process
    Divine.exe qui extrait tous les `.pak` de `scan_dir` lui-même, au lieu
    d'un lancement (et donc d'un démarrage Wine/CLR complet) par fichier.
    Bien plus représentatif d'un usage réel en lot.

    Sécurité : `scan_dir` (le dossier de mods réel, lu par Divine.exe via
    `-s`) n'est JAMAIS le dossier de destination — l'extraction va
    toujours dans un `tempfile.TemporaryDirectory` séparé (`-d`), donc
    aucune écriture n'a lieu sur les `.pak` sources ni dans leur dossier.

    Retourne `(records, temps_total_extraction_secondes)` : le temps total
    de l'unique appel Divine.exe n'est pas mesurable par fichier (un seul
    process pour tout le lot), donc chaque `record.index_or_extract_seconds`
    reçoit une valeur *amortie* (temps total / nombre de fichiers) — le
    temps brut est retourné séparément pour rester transparent plutôt que
    de le cacher derrière une moyenne."""
    if records is None:
        records = {}
    for pak_path in pak_paths:
        records[pak_path.name] = PakRecord(file=pak_path.name)

    with tempfile.TemporaryDirectory(prefix="bg3_compare_divine_batch_") as tmp:
        dest_root = Path(tmp)
        assert (
            dest_root.resolve() != scan_dir.resolve()
            and dest_root.resolve() not in scan_dir.resolve().parents
        ), (
            "la destination d'extraction ne doit jamais être (ou contenir) le dossier source des .pak"
        )

        use_wine_path = not is_windows()
        start = time.monotonic()
        try:
            _run_divine(
                divine_exe,
                [
                    "-g",
                    "bg3",
                    "-a",
                    "extract-packages",
                    "-s",
                    _path_arg(scan_dir, use_wine_path=use_wine_path),
                    "-d",
                    _path_arg(dest_root, use_wine_path=use_wine_path),
                    "-i",
                    "pak",
                    "--use-package-name",
                ],
                reference_path=reference_path,
                timeout=max(600, 5 * len(pak_paths)),
            )
        except PakMetadataError as exc:
            error = str(exc)
            for record in records.values():
                record.error = error
                if on_progress is not None:
                    on_progress(record)
            return records, time.monotonic() - start
        total_seconds = time.monotonic() - start

        for pak_path in pak_paths:
            record = records[pak_path.name]
            record.index_or_extract_seconds = total_seconds / len(pak_paths)
            work_dir = dest_root / pak_path.stem
            if not work_dir.is_dir():
                record.error = "non extrait par le batch Divine.exe (dossier de sortie absent)"
                if on_progress is not None:
                    on_progress(record)
                continue
            _finalize_divine_extraction(record, work_dir, sample_cap, reference_path=reference_path)
            if on_progress is not None:
                on_progress(record)

    return records, total_seconds


def _run_divine_tool(
    pak_paths: list[Path],
    sample_cap: int,
    *,
    divine_exe: Path,
    reference_path: Path,
    records: dict[str, PakRecord] | None = None,
    on_progress: Callable[[PakRecord], None] | None = None,
) -> dict[str, PakRecord]:
    """Un lancement de process Divine.exe *par `.pak`* (action `extract-
    package`, singulier) — le pire cas côté coût de démarrage (Wine/CLR
    relancé à chaque fichier), mais reflète un usage ponctuel isolé (ex:
    `pak_metadata.read_pak_identity`, appelé une seule fois à la demande
    dans BG3Tools, jamais en boucle serrée). Voir `_run_divine_batch_tool`
    pour l'action `extract-packages` (pluriel), qui amortit ce coût sur
    tout un lot en un seul process — bien plus représentatif d'une
    comparaison en lot comme celle-ci."""
    if records is None:
        records = {}
    with tempfile.TemporaryDirectory(prefix="bg3_compare_divine_") as tmp:
        tmp_root = Path(tmp)
        for pak_path in pak_paths:
            record = PakRecord(file=pak_path.name)
            records[pak_path.name] = record
            work_dir = tmp_root / pak_path.stem
            work_dir.mkdir(parents=True, exist_ok=True)
            start = time.monotonic()
            try:
                use_wine_path = not is_windows()
                _run_divine(
                    divine_exe,
                    [
                        "-g",
                        "bg3",
                        "-a",
                        "extract-package",
                        "-s",
                        _path_arg(pak_path, use_wine_path=use_wine_path),
                        "-d",
                        _path_arg(work_dir, use_wine_path=use_wine_path),
                    ],
                    reference_path=reference_path,
                )
            except PakMetadataError as exc:
                record.error = str(exc)
                shutil.rmtree(work_dir, ignore_errors=True)
                if on_progress is not None:
                    on_progress(record)
                continue
            record.index_or_extract_seconds = time.monotonic() - start

            _finalize_divine_extraction(record, work_dir, sample_cap, reference_path=reference_path)

            shutil.rmtree(work_dir, ignore_errors=True)
            if on_progress is not None:
                on_progress(record)
    return records


# --------------------------------------------------------------------------
# CLI : run
# --------------------------------------------------------------------------


def _resolve_pak_paths(args: argparse.Namespace, config) -> tuple[list[Path], Path | None]:
    """Retourne `(chemins_.pak, dossier_scanné)` — le dossier est `None`
    quand des `.pak` précis ont été passés en positionnels plutôt qu'un
    `--dir`/la config (le mode batch Divine.exe a besoin d'un vrai dossier
    à passer tel quel à `-s`, pas d'une liste arbitraire de fichiers)."""
    if args.paks:
        return [Path(p) for p in args.paks], None
    scan_dir = args.dir or config.appdata_mods_dir
    if not scan_dir.is_dir():
        raise SystemExit(
            f"Dossier introuvable : {scan_dir} (précise --dir ou configure bg3_appdata_dir)."
        )
    return sorted(scan_dir.glob("*.pak")), scan_dir


def cmd_run(args: argparse.Namespace) -> int:
    config = load_config()
    pak_paths, scan_dir = _resolve_pak_paths(args, config)
    if not pak_paths:
        print("Aucun .pak à traiter.")
        return 0

    divine_mode = getattr(args, "divine_mode", "per-file")
    if args.tool == "divine" and divine_mode == "batch" and scan_dir is None:
        print(
            "--divine-mode batch a besoin d'un vrai dossier à scanner "
            "(--dir, ou la config bg3_appdata_dir) — incompatible avec une liste de .pak explicite."
        )
        return 2

    print(
        f"[{args.tool}] {len(pak_paths)} .pak, échantillon de contenu = {args.sample}"
        + (", mode batch" if args.tool == "divine" and divine_mode == "batch" else "")
    )

    out_path = args.out or (REPORTS_DIR / f"{args.tool}_report.json")
    records: dict[str, PakRecord] = {}
    extra: dict[str, Any] = {}
    total = len(pak_paths)
    done = 0

    def flush(record: PakRecord) -> None:
        nonlocal done
        done += 1
        if args.verbose:
            if record.error:
                status = f"ERREUR : {record.error}"
            elif record.content_errors:
                status = f"{len(record.content_errors)} entrée(s) en erreur"
            else:
                status = "OK"
            print(
                f"  [{done}/{total}] {record.file} — "
                f"{record.index_or_extract_seconds:.2f}s index/extraction, "
                f"{record.content_seconds:.2f}s contenu — {status}",
                flush=True,
            )
        _write_report(out_path, args.tool, args.sample, records, extra=extra)

    if args.tool == "python":
        _run_python(pak_paths, args.sample, records=records, on_progress=flush)
    elif args.tool == "rust":
        _run_rust(pak_paths, args.sample, records=records, on_progress=flush)
    elif args.tool == "rust-native":
        _run_rust_native(pak_paths, args.sample, records=records, on_progress=flush)
    else:
        divine_exe = args.divine_exe or find_divine_exe(config.tools_dir)
        if divine_exe is None or not divine_exe.is_file():
            print(f"Divine.exe introuvable sous {config.tools_dir} — précise --divine-exe.")
            return 2
        reference_path = args.reference_path or config.appdata_path
        if not reference_path.is_dir():
            print(f"Chemin de référence introuvable : {reference_path} (précise --reference-path).")
            return 2
        if divine_mode == "batch":
            extra["divine_mode"] = "batch"
            _, batch_total_seconds = _run_divine_batch_tool(
                pak_paths,
                scan_dir,
                args.sample,
                divine_exe=divine_exe,
                reference_path=reference_path,
                records=records,
                on_progress=flush,
            )
            extra["batch_total_extract_seconds"] = batch_total_seconds
        else:
            extra["divine_mode"] = "per-file"
            _run_divine_tool(
                pak_paths,
                args.sample,
                divine_exe=divine_exe,
                reference_path=reference_path,
                records=records,
                on_progress=flush,
            )

    errors = sum(1 for r in records.values() if r.error)
    content_errors = sum(len(r.content_errors) for r in records.values())
    total_index = sum(r.index_or_extract_seconds for r in records.values())
    total_content = sum(r.content_seconds for r in records.values())
    total_hashed = sum(len(r.content_hashes) for r in records.values())
    print(
        f"[{args.tool}] terminé : {len(records)} .pak ({errors} en erreur, "
        f"{content_errors} entrées en erreur) — "
        f"index/extraction {total_index:.2f}s, contenu {total_content:.2f}s "
        f"({total_hashed} fichiers hashés)"
    )

    _write_report(out_path, args.tool, args.sample, records, extra=extra)
    print(f"[{args.tool}] rapport écrit : {out_path}")
    return 0


# --------------------------------------------------------------------------
# CLI : diff
# --------------------------------------------------------------------------


def _load_report(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _show_rust_native_overhead(present: dict[str, Any]) -> None:
    """Section indépendante du croisement structurel ci-dessous : compare,
    fichier par fichier, le timing `rust` (Python → PyO3 → bg3rustpaklib) à
    celui de `rust-native` (bg3rustpaklib appelé directement en Rust, sans
    Python/PyO3) pour quantifier le coût du binding FFI/PyO3 lui-même —
    le "manque connu" documenté dans
    `Tools/bg3rustpaklib/README.md#comparisons`. `rust-native` n'a pas
    d'`entries`/`content_hashes` exploitables, donc il est volontairement
    tenu à l'écart du croisement identité/fichiers/hash de `cmd_diff`."""
    rust_native = _load_report(REPORTS_DIR / "rust-native_report.json")
    rust = present.get("rust") or _load_report(REPORTS_DIR / "rust_report.json")
    if rust_native is None or rust is None:
        return

    common = sorted(set(rust["paks"]) & set(rust_native["paks"]))
    print("\nOverhead FFI/binding (rust = PyO3, rust-native = Rust pur) :")
    if not common:
        print("    aucun .pak commun entre rust_report.json et rust-native_report.json")
        return

    total_index_pyo3 = total_index_native = 0.0
    total_content_pyo3 = total_content_native = 0.0
    for pak in common:
        pyo3_rec = rust["paks"][pak]
        native_rec = rust_native["paks"][pak]
        if pyo3_rec.get("error") or native_rec.get("error"):
            continue
        total_index_pyo3 += pyo3_rec["index_or_extract_seconds"]
        total_index_native += native_rec["index_or_extract_seconds"]
        total_content_pyo3 += pyo3_rec["content_seconds"]
        total_content_native += native_rec["content_seconds"]
        print(
            f"    {pak}: index {native_rec['index_or_extract_seconds']:.4f}s natif vs "
            f"{pyo3_rec['index_or_extract_seconds']:.4f}s PyO3 "
            f"(overhead {pyo3_rec['index_or_extract_seconds'] - native_rec['index_or_extract_seconds']:+.4f}s), "
            f"contenu {native_rec['content_seconds']:.4f}s natif vs "
            f"{pyo3_rec['content_seconds']:.4f}s PyO3 "
            f"(overhead {pyo3_rec['content_seconds'] - native_rec['content_seconds']:+.4f}s)"
        )
    print(
        f"    TOTAL : index natif {total_index_native:.4f}s / PyO3 {total_index_pyo3:.4f}s "
        f"(overhead {total_index_pyo3 - total_index_native:+.4f}s) — "
        f"contenu natif {total_content_native:.4f}s / PyO3 {total_content_pyo3:.4f}s "
        f"(overhead {total_content_pyo3 - total_content_native:+.4f}s)"
    )


def cmd_diff(args: argparse.Namespace) -> int:
    tools = ["python", "rust", "divine"]
    reports = {t: _load_report(REPORTS_DIR / f"{t}_report.json") for t in tools}
    present = {t: r for t, r in reports.items() if r is not None}
    if len(present) < 2:
        print(f"Au moins 2 rapports nécessaires pour comparer (trouvés : {list(present)}).")
        print(f"Lance d'abord : python {sys.argv[0]} run --tool <python|rust|rust-native|divine>")
        return 2

    print(f"Rapports chargés : {', '.join(present)}\n")

    all_paks = sorted(set.union(*(set(r["paks"]) for r in present.values())))
    identity_mismatches: list[str] = []
    entry_mismatches: list[str] = []
    size_mismatches: list[str] = []
    content_mismatches: list[str] = []
    missing: list[str] = []

    for pak in all_paks:
        recs = {t: r["paks"].get(pak) for t, r in present.items()}
        available = {t: rec for t, rec in recs.items() if rec is not None and not rec.get("error")}
        if len(available) < 2:
            missing.append(pak)
            continue

        identities = {
            t: tuple(rec["identity"]) if rec.get("identity") else None
            for t, rec in available.items()
        }
        if len(set(identities.values())) > 1:
            identity_mismatches.append(f"{pak}: {identities}")

        entry_sets = {t: set(rec["entries"]) for t, rec in available.items()}
        reference_tool = "divine" if "divine" in entry_sets else next(iter(entry_sets))
        reference_set = entry_sets[reference_tool]
        for t, names in entry_sets.items():
            if t == reference_tool:
                continue
            missing_here = reference_set - names
            extra_here = names - reference_set
            if missing_here or extra_here:
                entry_mismatches.append(
                    f"{pak} [{t} vs {reference_tool}]: manquants={len(missing_here)} en_trop={len(extra_here)}"
                )

        common_names = set.intersection(*entry_sets.values()) if entry_sets else set()
        for name in sorted(common_names):
            sizes = {t: available[t]["entries"][name]["size"] for t in available}
            if len(set(sizes.values())) > 1:
                size_mismatches.append(f"{pak}:{name}: {sizes}")

        hash_sets = {t: rec["content_hashes"] for t, rec in available.items()}
        common_hashed = (
            set.intersection(*(set(h) for h in hash_sets.values())) if hash_sets else set()
        )
        for name in sorted(common_hashed):
            values = {t: hash_sets[t][name] for t in hash_sets}
            if len(set(values.values())) > 1:
                content_mismatches.append(f"{pak}:{name}: {values}")

    def _show(title: str, items: list[str]) -> None:
        print(f"{title} : {len(items)}")
        for item in items[:20]:
            print(f"    {item}")
        if len(items) > 20:
            print(f"    ... et {len(items) - 20} de plus")

    _show("Identités divergentes (UUID/Name)", identity_mismatches)
    _show("Tables de fichiers divergentes", entry_mismatches)
    _show("Tailles divergentes", size_mismatches)
    _show("Contenu décompressé divergent", content_mismatches)
    if missing:
        print(f".pak avec moins de 2 rapports exploitables : {len(missing)}")

    total_problems = (
        len(identity_mismatches)
        + len(entry_mismatches)
        + len(size_mismatches)
        + len(content_mismatches)
    )
    print(f"\n{'AUCUNE DIVERGENCE' if total_problems == 0 else f'{total_problems} DIVERGENCE(S)'}")

    _show_rust_native_overhead(present)

    return 1 if total_problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser(
        "run", help="Exécute un seul outil sur un lot de .pak et écrit son rapport"
    )
    run_parser.add_argument(
        "--tool", choices=["python", "rust", "rust-native", "divine"], required=True
    )
    run_parser.add_argument(
        "paks", nargs="*", type=Path, help="Fichiers .pak précis (sinon --dir/config)"
    )
    run_parser.add_argument("--dir", type=Path, help="Dossier à scanner (*.pak)")
    run_parser.add_argument(
        "--sample", type=int, default=60, help="Fichiers de contenu hashés par .pak (défaut 60)"
    )
    run_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Affiche une ligne de progression par .pak traité (nom, temps, statut) — "
        "utile sur un run long (ex: Divine.exe per-file) pour voir que ça avance.",
    )
    run_parser.add_argument(
        "--divine-exe", type=Path, help="Chemin vers Divine.exe (outil divine seulement)"
    )
    run_parser.add_argument(
        "--divine-mode",
        choices=["per-file", "batch"],
        default="per-file",
        help=(
            "Outil divine seulement : 'per-file' (défaut) lance Divine.exe une fois par .pak "
            "(extract-package) ; 'batch' lance Divine.exe une seule fois sur tout --dir "
            "(extract-packages, action batch native de LSLib) — amortit le coût de démarrage "
            "Wine/CLR sur tout le lot au lieu de le payer par fichier. Nécessite --dir "
            "(incompatible avec une liste de .pak explicite)."
        ),
    )
    run_parser.add_argument(
        "--reference-path", type=Path, help="Chemin de référence Proton/WINEPREFIX"
    )
    run_parser.add_argument(
        "--out", type=Path, help="Chemin du rapport JSON (défaut reports/<tool>_report.json)"
    )
    run_parser.set_defaults(func=cmd_run)

    diff_parser = sub.add_parser("diff", help="Croise les rapports déjà générés sous reports/")
    diff_parser.set_defaults(func=cmd_diff)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
