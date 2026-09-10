#!/usr/bin/env python3
"""Compare trois lecteurs de .pak BG3 (LSPK) — Python natif (`pak_reader`),
Rust natif (`pak_reader_rs`, crate `bg3rustpaklib` + PyO3) et Divine.exe —
chacun exécuté séparément avec son propre rapport JSON, puis un diff final
qui les croise (identité UUID/Name, liste des fichiers, tailles, hash
SHA-256 du contenu décompressé).

Deux étapes :

1. `run --tool {python,rust,divine}` : scanne des .pak, produit
   `reports/<tool>_report.json` (chronométrage inclus). Un run par outil,
   indépendant des autres — on peut relancer un seul outil sans repasser
   sur les autres.
2. `diff` : charge les rapports présents sous `reports/`, croise tout ce
   qui est commun entre outils (identité, table des fichiers, tailles,
   hash de contenu) et affiche les divergences + un résumé.

Usage :
    python scripts/compare_pak_reader.py run --tool python
    python scripts/compare_pak_reader.py run --tool rust
    python scripts/compare_pak_reader.py run --tool divine --divine-exe Tools/ExportTools/Tools/Divine.exe
    python scripts/compare_pak_reader.py diff

Le lecteur Rust doit être compilé au préalable :
    uv run maturin develop --manifest-path rust/pak_reader_rs/Cargo.toml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bg3_mod_tui.compat_framework import find_divine_exe
from bg3_mod_tui.config import load_config
from bg3_mod_tui.pak_metadata import PakMetadataError, _path_arg, _run_divine, parse_meta_lsx
from bg3_mod_tui.platform_utils import is_windows

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
_COMPRESSION_NAMES = {0: "aucune", 1: "zlib", 2: "lz4", 3: "zstd"}


@dataclass
class PakRecord:
    file: str
    error: str | None = None
    identity: tuple[str, str] | None = None
    entries: dict[str, dict[str, int]] = field(default_factory=dict)  # name -> {size, compression}
    index_or_extract_seconds: float = 0.0
    content_hashes: dict[str, str] = field(default_factory=dict)
    content_errors: dict[str, str] = field(default_factory=dict)  # nom d'entrée -> erreur (n'interrompt pas le run)
    content_seconds: float = 0.0


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pick_sample_names(entries: dict[str, dict[str, int]], cap: int) -> list[str]:
    """Échantillon stratifié par méthode de compression quand connue
    (python/rust), sinon réparti uniformément sur les noms triés (divine,
    qui n'expose pas cette info avant extraction). `meta.lsx`/`meta.lsf`
    toujours inclus."""
    names = sorted(entries)
    if len(names) <= cap:
        return names
    forced = [n for n in names if n.lower().endswith(("meta.lsx", "meta.lsf"))]
    picked = set(forced)
    by_method: dict[int, list[str]] = {}
    for n in names:
        by_method.setdefault(entries[n].get("compression", -1), []).append(n)
    methods = sorted(by_method)
    cursors = {m: 0 for m in methods}
    sample = list(forced)
    while len(sample) < cap and any(cursors[m] < len(by_method[m]) for m in methods):
        for m in methods:
            if len(sample) >= cap:
                break
            lst = by_method[m]
            while cursors[m] < len(lst) and lst[cursors[m]] in picked:
                cursors[m] += 1
            if cursors[m] < len(lst):
                sample.append(lst[cursors[m]])
                picked.add(lst[cursors[m]])
                cursors[m] += 1
    return sample


def _write_report(
    out_path: Path,
    tool: str,
    sample_cap: int,
    records: dict[str, PakRecord],
    *,
    extra: dict[str, Any] | None = None,
) -> None:
    """Écrit (ou réécrit) le rapport JSON à partir de `records` tel quel à
    l'instant de l'appel — appelée après chaque `.pak` traité (pas
    seulement une fois à la fin) pour qu'une interruption ou une erreur
    inattendue au milieu d'un lot laisse un rapport partiel exploitable au
    lieu de rien du tout (même principe que `_flush_orphans_progress`
    ailleurs dans le projet). `extra` : champs additionnels au niveau
    racine du rapport (ex: mode batch Divine.exe, temps total brut avant
    répartition par fichier) — jamais dans `paks[...]` pour ne pas être
    confondu avec les champs par-fichier existants."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "tool": tool,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_cap": sample_cap,
        **(extra or {}),
        "paks": {name: asdict(record) for name, record in records.items()},
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# Voie Python native (bg3_mod_tui.pak_reader)
# --------------------------------------------------------------------------

def _run_python(
    pak_paths: list[Path],
    sample_cap: int,
    *,
    records: dict[str, PakRecord] | None = None,
    on_progress: Callable[[], None] | None = None,
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
                on_progress()
            continue
        record.index_or_extract_seconds = time.monotonic() - start
        record.entries = {
            e.name.replace("\\", "/"): {"size": e.uncompressed_size, "compression": e.compression_method}
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
            on_progress()
    return records


# --------------------------------------------------------------------------
# Voie Rust native (pak_reader_rs)
# --------------------------------------------------------------------------

def _run_rust(
    pak_paths: list[Path],
    sample_cap: int,
    *,
    records: dict[str, PakRecord] | None = None,
    on_progress: Callable[[], None] | None = None,
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
                on_progress()
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
            on_progress()
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
        str(p.relative_to(work_dir)).replace("\\", "/"): p for p in work_dir.rglob("*") if p.is_file()
    }
    record.entries = {name: {"size": p.stat().st_size, "compression": -1} for name, p in disk_files.items()}

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
    on_progress: Callable[[], None] | None = None,
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
        assert dest_root.resolve() != scan_dir.resolve() and dest_root.resolve() not in scan_dir.resolve().parents, (
            "la destination d'extraction ne doit jamais être (ou contenir) le dossier source des .pak"
        )

        use_wine_path = not is_windows()
        start = time.monotonic()
        try:
            _run_divine(
                divine_exe,
                [
                    "-g", "bg3",
                    "-a", "extract-packages",
                    "-s", _path_arg(scan_dir, use_wine_path=use_wine_path),
                    "-d", _path_arg(dest_root, use_wine_path=use_wine_path),
                    "-i", "pak",
                    "-u",
                ],
                reference_path=reference_path,
                timeout=max(600, 5 * len(pak_paths)),
            )
        except PakMetadataError as exc:
            error = str(exc)
            for record in records.values():
                record.error = error
                if on_progress is not None:
                    on_progress()
            return records, time.monotonic() - start
        total_seconds = time.monotonic() - start

        for pak_path in pak_paths:
            record = records[pak_path.name]
            record.index_or_extract_seconds = total_seconds / len(pak_paths)
            work_dir = dest_root / pak_path.stem
            if not work_dir.is_dir():
                record.error = "non extrait par le batch Divine.exe (dossier de sortie absent)"
                if on_progress is not None:
                    on_progress()
                continue
            _finalize_divine_extraction(record, work_dir, sample_cap, reference_path=reference_path)
            if on_progress is not None:
                on_progress()

    return records, total_seconds


def _run_divine_tool(
    pak_paths: list[Path],
    sample_cap: int,
    *,
    divine_exe: Path,
    reference_path: Path,
    records: dict[str, PakRecord] | None = None,
    on_progress: Callable[[], None] | None = None,
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
                        "-g", "bg3",
                        "-a", "extract-package",
                        "-s", _path_arg(pak_path, use_wine_path=use_wine_path),
                        "-d", _path_arg(work_dir, use_wine_path=use_wine_path),
                    ],
                    reference_path=reference_path,
                )
            except PakMetadataError as exc:
                record.error = str(exc)
                shutil.rmtree(work_dir, ignore_errors=True)
                if on_progress is not None:
                    on_progress()
                continue
            record.index_or_extract_seconds = time.monotonic() - start

            _finalize_divine_extraction(record, work_dir, sample_cap, reference_path=reference_path)

            shutil.rmtree(work_dir, ignore_errors=True)
            if on_progress is not None:
                on_progress()
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
        raise SystemExit(f"Dossier introuvable : {scan_dir} (précise --dir ou configure bg3_appdata_dir).")
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
    flush = lambda: _write_report(out_path, args.tool, args.sample, records)  # noqa: E731
    extra: dict[str, Any] = {}

    if args.tool == "python":
        _run_python(pak_paths, args.sample, records=records, on_progress=flush)
    elif args.tool == "rust":
        _run_rust(pak_paths, args.sample, records=records, on_progress=flush)
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


def cmd_diff(args: argparse.Namespace) -> int:
    tools = ["python", "rust", "divine"]
    reports = {t: _load_report(REPORTS_DIR / f"{t}_report.json") for t in tools}
    present = {t: r for t, r in reports.items() if r is not None}
    if len(present) < 2:
        print(f"Au moins 2 rapports nécessaires pour comparer (trouvés : {list(present)}).")
        print(f"Lance d'abord : python {sys.argv[0]} run --tool <python|rust|divine>")
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

        identities = {t: tuple(rec["identity"]) if rec.get("identity") else None for t, rec in available.items()}
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
        common_hashed = set.intersection(*(set(h) for h in hash_sets.values())) if hash_sets else set()
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

    total_problems = len(identity_mismatches) + len(entry_mismatches) + len(size_mismatches) + len(content_mismatches)
    print(f"\n{'AUCUNE DIVERGENCE' if total_problems == 0 else f'{total_problems} DIVERGENCE(S)'}")
    return 1 if total_problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Exécute un seul outil sur un lot de .pak et écrit son rapport")
    run_parser.add_argument("--tool", choices=["python", "rust", "divine"], required=True)
    run_parser.add_argument("paks", nargs="*", type=Path, help="Fichiers .pak précis (sinon --dir/config)")
    run_parser.add_argument("--dir", type=Path, help="Dossier à scanner (*.pak)")
    run_parser.add_argument("--sample", type=int, default=60, help="Fichiers de contenu hashés par .pak (défaut 60)")
    run_parser.add_argument("--divine-exe", type=Path, help="Chemin vers Divine.exe (outil divine seulement)")
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
    run_parser.add_argument("--reference-path", type=Path, help="Chemin de référence Proton/WINEPREFIX")
    run_parser.add_argument("--out", type=Path, help="Chemin du rapport JSON (défaut reports/<tool>_report.json)")
    run_parser.set_defaults(func=cmd_run)

    diff_parser = sub.add_parser("diff", help="Croise les rapports déjà générés sous reports/")
    diff_parser.set_defaults(func=cmd_diff)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
