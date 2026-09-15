"""Génère le rapport de benchmark (Markdown + PNG matplotlib) à partir des
rapports JSON déjà écrits sous `reports/` (lecture : `python_report.json`,
`rust_report.json`, `rust-native_report.json`, `divine_report.json` —
convention de `compare_pak_reader.py` ; création/édition :
`pak_bench_create_edit_report.json` — convention de `pak_bench_cli.py`).

Méthodologie "dans son jus" vs "pipeline réel" (décision explicite de
l'utilisateur, cf. spec) : pour CHAQUE outil qui a les deux, le rapport et
les graphes montrent deux séries côte à côte plutôt qu'un seul chiffre
mélangé — voir `scripts/pak_bench/strings.py` pour les labels exacts et
`docs/superpowers/specs/2026-09-15-pak-tools-benchmark-design.md` §3.b
pour le détail par outil.

Les textes longs (titres, labels, gabarits Markdown) vivent dans
`scripts/pak_bench/strings.py`, pas en littéraux inline ici.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.pak_bench import strings
from scripts.pak_bench.common import REPORTS_DIR, load_merged_tool_report, median

TOOL_COLORS = {
    "python": "#4C72B0",
    "bg3pythonpaklib": "#4C72B0",
    "rust": "#DD8452",
    "rust-pipeline": "#DD8452",
    "rust-native": "#55A868",
    "bg3rustpaklib": "#55A868",
    "divine": "#C44E52",
    "Divine.exe": "#C44E52",
    "divine-native": "#8172B2",
}


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_read_reports(reports_dir: Path = REPORTS_DIR) -> dict[str, dict[str, Any]]:
    """Un outil peut avoir plusieurs rapports (un par dossier/sous-ensemble
    mesuré, ex. `rust-native_data_report.json` + `rust-native_mods_report.json`
    en plus du fichier canonique `rust-native_report.json`) — tous fusionnés
    automatiquement par `load_merged_tool_report`, pas besoin de les
    combiner à la main après un batch portant sur plusieurs dossiers."""
    tools = ["python", "rust", "rust-native", "divine"]
    out = {}
    for t in tools:
        data = load_merged_tool_report(t, reports_dir)
        if data is not None:
            out[t] = data
    return out


def load_create_edit_report(reports_dir: Path = REPORTS_DIR) -> list[dict[str, Any]]:
    data = _load_json(reports_dir / "pak_bench_create_edit_report.json")
    if data is None:
        return []
    return data.get("results", [])


def summarize_read_report(report: dict[str, Any]) -> dict[str, float]:
    """Totaux index/contenu (secondes) et nombre de .pak en erreur pour un
    rapport de lecture (`compare_pak_reader.py --tool ...`)."""
    paks = report.get("paks", {})
    index_total = sum(p.get("index_or_extract_seconds", 0.0) for p in paks.values())
    content_total = sum(p.get("content_seconds", 0.0) for p in paks.values())
    errors = sum(1 for p in paks.values() if p.get("error"))
    return {
        "index_seconds": index_total,
        "content_seconds": content_total,
        "total_seconds": index_total + content_total,
        "pak_count": len(paks),
        "errors": errors,
    }


def summarize_create_edit(results: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, float]]:
    """Regroupe par (tool, scenario) : médiane du `total_seconds`, min,
    max, nombre d'échecs (`error` non nul) et taux de succès de la
    vérification round-trip (`verify_ok`)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in results:
        groups.setdefault((r["tool"], r["scenario"]), []).append(r)

    out: dict[tuple[str, str], dict[str, float]] = {}
    for key, items in groups.items():
        ok = [i for i in items if not i.get("error")]
        times = [i["total_seconds"] for i in ok]
        out[key] = {
            "n": len(items),
            "n_errors": len(items) - len(ok),
            "median_seconds": median(times),
            "min_seconds": min(times) if times else 0.0,
            "max_seconds": max(times) if times else 0.0,
            "verify_ok_rate": (sum(1 for i in ok if i.get("verify_ok")) / len(ok)) if ok else 0.0,
        }
    return out


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def render_markdown(
    read_reports: dict[str, dict[str, Any]],
    create_edit_results: list[dict[str, Any]],
    *,
    capability_matrix: str = strings.CAPABILITY_MATRIX_MD,
) -> str:
    """Les sections "narratives" (fix archive solide, bug Divine.exe batch,
    lien dashboard) sont des faits stables sur ce chantier plutôt que des
    annotations manuelles perdues à chaque régénération — les compteurs
    qu'elles citent (erreurs, .pak couverts) restent calculés depuis les
    rapports plutôt que figés en dur, pour ne pas devenir faux si le
    périmètre mesuré change."""
    read_summaries = {tool: summarize_read_report(r) for tool, r in read_reports.items()}
    pak_counts = {s["pak_count"] for s in read_summaries.values() if s["pak_count"] > 0}
    max_pak_count = max(pak_counts) if pak_counts else 0

    lines: list[str] = []
    lines.append(strings.REPORT_TITLE)
    lines.append("")
    lines.append(strings.REPORT_INTRO)
    lines.append("")
    lines.append(strings.DASHBOARD_LINK_LINE)
    lines.append("")
    lines.append(strings.SECTION_CAPABILITY_MATRIX)
    lines.append("")
    lines.append(capability_matrix)
    lines.append("")

    lines.append(strings.SECTION_READ)
    lines.append("")
    if not read_reports:
        lines.append(strings.READ_TABLE_EMPTY)
    else:
        lines.append(strings.READ_TABLE_HEADER)
        lines.append(strings.READ_TABLE_SEP)
        for tool in read_reports:
            label, mode = strings.READ_MODE_LABELS.get(tool, (tool, tool))
            s = read_summaries[tool]
            footnotes = ""
            if tool in ("python", "rust", "rust-native"):
                footnotes += "¹"
                if tool == "rust":
                    footnotes += "²"
            elif tool == "divine":
                if s["pak_count"] and s["pak_count"] < max_pak_count:
                    footnotes += "³"
                if s["errors"]:
                    footnotes += "⁴"
            lines.append(
                f"| {label} | {mode} | {s['pak_count']:.0f} | {s['errors']:.0f}{footnotes} | "
                f"{s['index_seconds']:.3f} | {s['content_seconds']:.3f} | "
                f"{s['total_seconds']:.3f} |"
            )
        lines.append("")
        if "python" in read_summaries or "rust-native" in read_summaries:
            n_continuation = read_summaries.get(
                "rust-native", read_summaries.get("python", {})
            ).get("errors", 0)
            lines.append(strings.READ_FOOTNOTE_CONTINUATION_FILES.format(n=int(n_continuation)))
        if "rust" in read_summaries and "rust-native" in read_summaries:
            n_extra = read_summaries["rust"]["errors"] - read_summaries["rust-native"]["errors"]
            if n_extra > 0:
                lines.append("")
                lines.append(strings.READ_FOOTNOTE_LOWTEX_PIPELINE.format(n_extra=int(n_extra)))
        if "divine" in read_summaries:
            ds = read_summaries["divine"]
            if ds["pak_count"] and ds["pak_count"] < max_pak_count:
                lines.append("")
                lines.append(
                    strings.READ_FOOTNOTE_DIVINE_SCOPE.format(
                        pak_count=int(ds["pak_count"]), other_count=int(max_pak_count)
                    )
                )
            if ds["errors"]:
                lines.append("")
                lines.append(
                    strings.READ_FOOTNOTE_DIVINE_ERRORS.format(
                        n_errors=int(ds["errors"]), pak_count=int(ds["pak_count"])
                    )
                )
    lines.append("")

    lines.append(strings.SECTION_CREATE_EDIT)
    lines.append("")
    if not create_edit_results:
        lines.append(strings.CREATE_EDIT_TABLE_EMPTY)
    else:
        summary = summarize_create_edit(create_edit_results)
        lines.append(strings.CREATE_EDIT_TABLE_HEADER)
        lines.append(strings.CREATE_EDIT_TABLE_SEP)
        for (tool, scenario), s in sorted(summary.items()):
            lines.append(
                f"| {tool} | {scenario} | {s['n']:.0f} | {s['n_errors']:.0f} | "
                f"{s['median_seconds']:.4f} | {s['min_seconds']:.4f} | {s['max_seconds']:.4f} | "
                f"{s['verify_ok_rate'] * 100:.0f}% |"
            )
        lines.append("")
        lines.append(strings.CREATE_EDIT_PYTHONPAKLIB_NOTE)
    lines.append("")

    if "rust-native" in read_summaries:
        lines.append(strings.SECTION_SOLID_ARCHIVE_FIX)
        lines.append("")
        lines.append(strings.SOLID_ARCHIVE_FIX_BODY)
        lines.append("")

    if "divine" in read_summaries:
        lines.append(strings.SECTION_DIVINE_BATCH_BUG)
        lines.append("")
        lines.append(strings.DIVINE_BATCH_BUG_BODY)
        lines.append("")

    lines.append(strings.SECTION_LIMITATIONS)
    lines.append("")
    if create_edit_results:
        lines.append(f"- {strings.LIMITATION_CREATE_EDIT_DIVINE_SKIPPED}")
    if "divine" in read_summaries and read_summaries["divine"]["pak_count"] < max_pak_count:
        lines.append(
            "- "
            + strings.LIMITATION_DIVINE_SCOPE_TEMPLATE.format(
                pak_count=int(read_summaries["divine"]["pak_count"]),
                other_count=int(max_pak_count),
            )
        )
    lines.append(f"- {strings.LIMITATION_DIVINE_WINE}")
    lines.append("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# PNG (matplotlib) — barres groupées outil x scénario, séries natif/pipeline
# --------------------------------------------------------------------------


def render_read_chart(read_reports: dict[str, dict[str, Any]], out_path: Path) -> bool:
    """Retourne False (et n'écrit rien) si matplotlib est absent ou s'il
    n'y a rien à tracer — jamais une exception qui ferait échouer tout le
    rapport pour un module optionnel."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    if not read_reports:
        return False

    order = [t for t in ["python", "rust-native", "rust", "divine"] if t in read_reports]
    labels = [strings.READ_CHART_MODE_LABELS[t] for t in order]
    index_vals = [summarize_read_report(read_reports[t])["index_seconds"] for t in order]
    content_vals = [summarize_read_report(read_reports[t])["content_seconds"] for t in order]

    fig, ax = plt.subplots(figsize=(max(6, 1.6 * len(order) + 2), 5))
    x = range(len(order))
    width = 0.35
    ax.bar(
        [i - width / 2 for i in x],
        index_vals,
        width,
        label=strings.READ_CHART_SERIES_INDEX,
        color="#4C72B0",
    )
    ax.bar(
        [i + width / 2 for i in x],
        content_vals,
        width,
        label=strings.READ_CHART_SERIES_CONTENT,
        color="#DD8452",
    )
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel(strings.READ_CHART_YLABEL)
    ax.set_title(strings.READ_CHART_TITLE)
    ax.legend()
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return True


def render_create_edit_chart(create_edit_results: list[dict[str, Any]], out_path: Path) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    if not create_edit_results:
        return False

    summary = summarize_create_edit(create_edit_results)
    scenarios = sorted({scenario for _tool, scenario in summary})
    tools = sorted({tool for tool, _scenario in summary})
    if not scenarios or not tools:
        return False

    fig, ax = plt.subplots(figsize=(max(7, 1.8 * len(scenarios) + 2), 5))
    n_tools = len(tools)
    width = 0.8 / max(1, n_tools)
    x_base = range(len(scenarios))
    for i, tool in enumerate(tools):
        vals = [summary.get((tool, sc), {}).get("median_seconds", 0.0) for sc in scenarios]
        offset = (i - (n_tools - 1) / 2) * width
        ax.bar(
            [xb + offset for xb in x_base],
            vals,
            width,
            label=tool,
            color=TOOL_COLORS.get(tool, None),
        )
    ax.set_xticks(list(x_base))
    ax.set_xticklabels(scenarios)
    ax.set_ylabel(strings.CREATE_EDIT_CHART_YLABEL)
    ax.set_title(strings.CREATE_EDIT_CHART_TITLE)
    ax.legend()
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return True
