#!/usr/bin/env python3
"""Point d'entrée CLI pour les scénarios création/édition/batch et la
génération du rapport du benchmark .pak BG3. Voir `scripts/pak_bench/
strings.py` pour la description longue (`CLI_DESCRIPTION`, aide des
sous-commandes) — centralisée là plutôt qu'en docstring inline, comme le
reste des textes longs de ce chantier."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bg3_mod_tui.compat_framework import find_divine_exe
from bg3_mod_tui.config import load_config
from scripts.pak_bench import create_edit, export_dashboard_data, strings, synthetic
from scripts.pak_bench import report as report_mod
from scripts.pak_bench.common import REPORTS_DIR, ScenarioResult, write_scenario_report

DOCS_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "docs" / "pak-tools-benchmark"


def _default_divine_exe(config) -> Path | None:
    return find_divine_exe(config.tools_dir)


def cmd_fixtures(args: argparse.Namespace) -> int:
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for i in range(args.count):
        profile = ["small-many", "large-few", "mixed"][i % 3]
        source_dir = out_dir / f"source_{i}"
        n = synthetic.generate_source_tree(source_dir, profile=profile, seed=i)
        total += n
        print(f"  source_{i} ({profile}) : {n} fichiers -> {source_dir}")
    print(f"Fixtures générées sous {out_dir} ({total} fichiers au total).")
    return 0


def _synthetic_sources(tmp_root: Path, count: int) -> list[Path]:
    sources = []
    for i in range(count):
        profile = ["small-many", "large-few", "mixed"][i % 3]
        source_dir = tmp_root / f"source_{i}"
        synthetic.generate_source_tree(source_dir, profile=profile, seed=i)
        sources.append(source_dir)
    return sources


def _resolve_sources(args: argparse.Namespace, tmp_root: Path) -> list[Path] | None:
    sources = _synthetic_sources(tmp_root, args.count) if args.synthetic else args.source_dirs
    if not sources:
        print(strings.MSG_NO_SOURCE_DIRS)
        return None
    return sources


def _print_run(tool: str, scenario: str, label: str, r: ScenarioResult) -> None:
    status = "OK" if not r.error else f"ERREUR: {r.error[:120]}"
    print(f"  [{tool}] {scenario} {label}: {r.total_seconds:.4f}s — {status}")


def cmd_create(args: argparse.Namespace) -> int:
    config = load_config()
    results: list[ScenarioResult] = []

    with tempfile.TemporaryDirectory(prefix="bg3_pak_bench_create_") as tmp:
        tmp_root = Path(tmp)
        sources = _resolve_sources(args, tmp_root)
        if sources is None:
            return 2

        out_dir = tmp_root / "out"
        out_dir.mkdir(exist_ok=True)

        divine_exe = None if args.skip_divine else (args.divine_exe or _default_divine_exe(config))
        reference_path = None if args.skip_divine else (args.reference_path or config.appdata_path)
        divine_available = bool(
            divine_exe and divine_exe.is_file() and reference_path and reference_path.is_dir()
        )
        if not args.skip_divine and not divine_available:
            print(strings.MSG_DIVINE_SKIPPED)

        for run in range(args.repeat):
            pairs = [(src, out_dir / f"{src.name}_run{run}.pak") for src in sources]

            for src, dst in pairs:
                r = create_edit.rust_create_single(src, dst, version=args.version)
                results.append(r)
                _print_run("bg3rustpaklib", "create-single", f"{src.name} run{run}", r)

            if len(pairs) > 1:
                batch_pairs = [(src, out_dir / f"{src.name}_batch_run{run}.pak") for src in sources]
                results.extend(create_edit.rust_create_batch(batch_pairs, version=args.version))

            if divine_available:
                for src, dst in pairs:
                    dst_divine = dst.with_name(dst.stem + "_divine.pak")
                    r = create_edit.divine_create_single(
                        src, dst_divine, divine_exe=divine_exe, reference_path=reference_path
                    )
                    results.append(r)
                    _print_run("Divine.exe", "create-single", f"{src.name} run{run}", r)

    out_path = args.out or (REPORTS_DIR / "pak_bench_create_edit_report.json")
    _merge_and_write(out_path, results)
    print(strings.MSG_REPORT_WRITTEN.format(path=out_path))
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    config = load_config()
    results: list[ScenarioResult] = []

    with tempfile.TemporaryDirectory(prefix="bg3_pak_bench_edit_") as tmp:
        tmp_root = Path(tmp)
        sources = _resolve_sources(args, tmp_root)
        if sources is None:
            return 2

        work = tmp_root / "work"
        work.mkdir(exist_ok=True)

        # Base .pak à éditer : créé une fois via bg3rustpaklib (rapide, natif).
        base_paks = []
        overlays = []
        for src in sources:
            base_pak = work / f"{src.name}_base.pak"
            create_edit._run_native_timing(["create", str(src), str(base_pak), args.version])
            overlay_dir = work / f"{src.name}_overlay"
            synthetic.generate_overlay_tree(
                src, overlay_dir, fraction=args.overlay_fraction, seed=1
            )
            base_paks.append(base_pak)
            overlays.append(overlay_dir)

        divine_exe = None if args.skip_divine else (args.divine_exe or _default_divine_exe(config))
        reference_path = None if args.skip_divine else (args.reference_path or config.appdata_path)
        divine_available = bool(
            divine_exe and divine_exe.is_file() and reference_path and reference_path.is_dir()
        )
        if not args.skip_divine and not divine_available:
            print(strings.MSG_DIVINE_SKIPPED)

        for run in range(args.repeat):
            triples = [
                (base_paks[i], overlays[i], work / f"{sources[i].name}_edited_run{run}.pak")
                for i in range(len(sources))
            ]
            for input_pak, overlay_dir, output_pak in triples:
                r = create_edit.rust_edit_single(
                    input_pak, overlay_dir, output_pak, version=args.version
                )
                results.append(r)
                _print_run("bg3rustpaklib", "edit-single", output_pak.name, r)

            if len(triples) > 1:
                batch_triples = [
                    (
                        base_paks[i],
                        overlays[i],
                        work / f"{sources[i].name}_edited_batch_run{run}.pak",
                    )
                    for i in range(len(sources))
                ]
                results.extend(create_edit.rust_edit_batch(batch_triples, version=args.version))

            if divine_available:
                for i, (input_pak, overlay_dir, output_pak) in enumerate(triples):
                    divine_work = work / f"divine_edit_work_{i}_{run}"
                    divine_work.mkdir(exist_ok=True)
                    output_divine = output_pak.with_name(output_pak.stem + "_divine.pak")
                    r = create_edit.divine_edit_single(
                        input_pak,
                        overlay_dir,
                        output_divine,
                        divine_exe=divine_exe,
                        reference_path=reference_path,
                        work_dir=divine_work,
                    )
                    results.append(r)
                    _print_run("Divine.exe", "edit-single", output_divine.name, r)

    out_path = args.out or (REPORTS_DIR / "pak_bench_create_edit_report.json")
    _merge_and_write(out_path, results)
    print(strings.MSG_REPORT_WRITTEN.format(path=out_path))
    return 0


def _merge_and_write(out_path: Path, new_results: list[ScenarioResult]) -> None:
    """Fusionne avec un rapport existant (create et edit écrivent le même
    fichier) plutôt que de s'écraser l'un l'autre."""
    from scripts.pak_bench.common import load_scenario_report

    existing = load_scenario_report(out_path)
    existing_objs = [ScenarioResult(**e) for e in existing]
    write_scenario_report(out_path, existing_objs + new_results)


def cmd_report(args: argparse.Namespace) -> int:
    read_reports = report_mod.load_read_reports()
    create_edit_results = report_mod.load_create_edit_report()

    md = report_mod.render_markdown(read_reports, create_edit_results)
    md_path = args.out_dir / "pak_tools_benchmark.md"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    print(strings.MSG_MARKDOWN_WRITTEN.format(path=md_path))

    read_png = args.out_dir / "pak_tools_benchmark_read.png"
    if report_mod.render_read_chart(read_reports, read_png):
        print(strings.MSG_READ_CHART_WRITTEN.format(path=read_png))
    else:
        print(strings.MSG_READ_CHART_SKIPPED)

    ce_png = args.out_dir / "pak_tools_benchmark_create_edit.png"
    if report_mod.render_create_edit_chart(create_edit_results, ce_png):
        print(strings.MSG_CE_CHART_WRITTEN.format(path=ce_png))
    else:
        print(strings.MSG_CE_CHART_SKIPPED)

    if args.update_dashboard:
        DOCS_DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
        docs_md = DOCS_DASHBOARD_DIR / "pak_tools_benchmark.md"
        docs_md.write_text(md, encoding="utf-8")
        print(strings.MSG_DASHBOARD_MD_COPIED.format(path=docs_md))

        for src, name in (
            (read_png, "pak_tools_benchmark_read.png"),
            (ce_png, "pak_tools_benchmark_create_edit.png"),
        ):
            if src.is_file():
                (DOCS_DASHBOARD_DIR / name).write_bytes(src.read_bytes())

        payload = export_dashboard_data.build_dashboard_payload(REPORTS_DIR)
        dashboard_data_path = REPORTS_DIR / "dashboard_data.json"
        dashboard_data_path.parent.mkdir(parents=True, exist_ok=True)
        dashboard_data_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

        dashboard_html = DOCS_DASHBOARD_DIR / "dashboard.html"
        if dashboard_html.is_file():
            export_dashboard_data.update_html_dashboard(dashboard_html, payload)
            print(strings.MSG_DASHBOARD_HTML_UPDATED.format(path=dashboard_html))
        else:
            print(strings.MSG_DASHBOARD_HTML_MISSING.format(path=dashboard_html))

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=strings.CLI_DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fx = sub.add_parser("fixtures", help=strings.HELP_FIXTURES)
    fx.add_argument("--out-dir", type=Path, default=Path("reports") / "pak_bench_fixtures")
    fx.add_argument("--count", type=int, default=3)
    fx.set_defaults(func=cmd_fixtures)

    for name, fn, extra, help_text in (
        ("create", cmd_create, False, strings.HELP_CREATE),
        ("edit", cmd_edit, True, strings.HELP_EDIT),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("source_dirs", nargs="*", type=Path, help=strings.HELP_SOURCE_DIRS)
        p.add_argument("--synthetic", action="store_true", help=strings.HELP_SYNTHETIC)
        p.add_argument("--count", type=int, default=3, help=strings.HELP_COUNT_SYNTHETIC)
        p.add_argument("--repeat", type=int, default=3, help=strings.HELP_REPEAT)
        p.add_argument("--version", choices=["v15", "v16", "v18"], default="v18")
        p.add_argument("--skip-divine", action="store_true", help=strings.HELP_SKIP_DIVINE)
        p.add_argument("--divine-exe", type=Path)
        p.add_argument("--reference-path", type=Path)
        p.add_argument("--out", type=Path)
        if extra:
            p.add_argument(
                "--overlay-fraction", type=float, default=0.1, help=strings.HELP_OVERLAY_FRACTION
            )
        p.set_defaults(func=fn)

    rp = sub.add_parser("report", help=strings.HELP_REPORT)
    rp.add_argument("--out-dir", type=Path, default=Path("reports"))
    rp.add_argument("--update-dashboard", action="store_true", help=strings.HELP_UPDATE_DASHBOARD)
    rp.set_defaults(func=cmd_report)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
