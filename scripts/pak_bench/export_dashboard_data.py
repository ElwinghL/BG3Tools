"""Consolide les rapports JSON de `reports/*.json` (lecture + création/édition)
en un unique fichier JSON compact, pensé pour être embarqué tel quel dans un
Artifact HTML autonome (dashboard interactif) — pas pour remplacer
`scripts/pak_bench/report.py` (Markdown + PNG), qui reste la sortie versionnée.

Volontairement strippé des champs volumineux et non pertinents pour un
dashboard (`content_hashes`, le détail des `entries` par fichier) : seuls le
nombre d'entrées, les temps et le statut d'erreur (première ligne seulement,
les logs Wine étant très verbeux) sont conservés par `.pak`.

Usage :
    uv run python -m scripts.pak_bench.export_dashboard_data [--out PATH]

Par défaut écrit `reports/dashboard_data.json` (dossier gitignored,
régénérable depuis les rapports bruts eux-mêmes gitignored).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.pak_bench.common import REPORTS_DIR, median

# (préfixe de fichier, clé outil dans le dashboard, libellé) — le "mode"
# (data/mods/...) est déduit dynamiquement du nom de fichier, pas figé ici :
# tout `{préfixe}_<mode>_report.json` sous `reports/` est repris
# automatiquement, plus le fichier canonique `{préfixe}_report.json` (mode
# "combiné"). Ça évite d'oublier un dataset ou de devoir modifier ce fichier
# à chaque nouveau dossier/lot mesuré (cause du bug du 2026-09-15 : liste
# figée qui ignorait silencieusement tout fichier non prévu à l'avance).
TOOL_PREFIXES: list[tuple[str, str, str]] = [
    ("rust-native", "rust_native", "bg3rustpaklib (natif)"),
    ("rust", "rust_pipeline", "bg3rustpaklib (pipeline PyO3)"),
    ("python", "python", "bg3pythonpaklib"),
    ("divine", "divine", "Divine.exe"),
]

# Rapports Divine.exe en échec total connus, documentés séparément plutôt
# que mélangés aux séries de succès (traçabilité d'anciennes tentatives).
DIVINE_FAILED_REPORTS = ["divine_batch_FAILED_attempt.json"]


def _discover_read_reports(reports_dir: Path) -> list[tuple[Path, str, str, str]]:
    """Retourne (chemin, clé outil, libellé, mode) pour chaque
    `reports/*_report.json` reconnu — le "mode" est le segment entre le
    préfixe outil et `_report.json` (ex. "data", "mods"), ou "combiné" pour
    le fichier canonique sans segment. `divine_batch_report.json` (échec
    connu, cf. DIVINE_FAILED_REPORTS) est exclu ici pour ne pas apparaître
    deux fois."""
    found: list[tuple[Path, str, str, str]] = []
    for path in sorted(reports_dir.glob("*_report.json")):
        if path.name in DIVINE_FAILED_REPORTS or path.name == "pak_bench_create_edit_report.json":
            continue
        # préfixes triés du plus long au plus court pour que "rust-native"
        # matche avant "rust" (sinon rust-native_*.json serait mal classé).
        for prefix, tool_key, label in sorted(TOOL_PREFIXES, key=lambda t: len(t[0]), reverse=True):
            if not path.name.startswith(prefix + "_"):
                continue
            rest = path.name[len(prefix) + 1 :]
            if rest == "report.json":
                mode = "combiné"
            elif rest.endswith("_report.json"):
                mode = rest[: -len("_report.json")]
            else:
                continue
            found.append((path, tool_key, label, mode))
            break
    return found


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _first_line(err: str | None, limit: int = 160) -> str | None:
    if not err:
        return None
    line = err.splitlines()[0].strip()
    return line[:limit]


def build_read_detail(reports_dir: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Retourne (lignes de détail par .pak, résumés agrégés par (tool,mode))."""
    per_pak: dict[tuple[str, str], dict[str, Any]] = {}
    summaries: dict[str, dict[str, Any]] = {}

    for path, tool_key, label, mode in _discover_read_reports(reports_dir):
        data = _load(path)
        if data is None:
            continue
        paks = data.get("paks", {})
        index_total = 0.0
        content_total = 0.0
        n_errors = 0
        for pak_name, rec in paks.items():
            key = (mode, pak_name)
            row = per_pak.setdefault(
                key,
                {"pak": pak_name, "dataset": mode, "tools": {}},
            )
            err = rec.get("error")
            idx_s = rec.get("index_or_extract_seconds") or 0.0
            content_s = rec.get("content_seconds") or 0.0
            row["tools"][tool_key] = {
                "error": _first_line(err),
                "index_s": round(idx_s, 6),
                "content_s": round(content_s, 6),
                "entries": len(rec.get("entries") or {}),
            }
            index_total += idx_s
            content_total += content_s
            if err:
                n_errors += 1
        summary_key = f"{tool_key}:{mode}"
        prev = summaries.get(summary_key)
        if prev is None:
            summaries[summary_key] = {
                "tool": tool_key,
                "label": label,
                "mode": mode,
                "pak_count": len(paks),
                "errors": n_errors,
                "index_seconds": round(index_total, 4),
                "content_seconds": round(content_total, 4),
                "total_seconds": round(index_total + content_total, 4),
                "generated_at": data.get("generated_at"),
            }
        else:
            # Ne devrait pas arriver (un seul fichier par (tool,mode)) mais
            # on fusionne proprement si jamais deux fichiers se recouvrent.
            prev["pak_count"] += len(paks)
            prev["errors"] += n_errors
            prev["index_seconds"] = round(prev["index_seconds"] + index_total, 4)
            prev["content_seconds"] = round(prev["content_seconds"] + content_total, 4)
            prev["total_seconds"] = round(prev["total_seconds"] + index_total + content_total, 4)

    detail_rows = sorted(per_pak.values(), key=lambda r: (r["dataset"], r["pak"]))
    return detail_rows, summaries


def build_divine_incomplete_status(reports_dir: Path) -> dict[str, Any]:
    """Documente le périmètre réel de la série Divine.exe (souvent
    partielle : mode per-file lent, mode batch natif cassé en amont, cf.
    `docs/pak-tools-benchmark/pak_tools_benchmark.md`) et les tentatives
    antérieures en échec total connues (`DIVINE_FAILED_REPORTS`), pour ne
    pas les mélanger aux chiffres de succès affichés ailleurs dans le
    dashboard."""
    attempts = []
    for fname in DIVINE_FAILED_REPORTS:
        data = _load(reports_dir / fname)
        if data is None:
            continue
        paks = data.get("paks", {})
        n_errors = sum(1 for v in paks.values() if v.get("error"))
        sample_err = next((v.get("error") for v in paks.values() if v.get("error")), None)
        attempts.append(
            {
                "file": fname,
                "generated_at": data.get("generated_at"),
                "pak_count": len(paks),
                "errors": n_errors,
                "sample_error": _first_line(sample_err, 200),
            }
        )

    # Chiffres réels de la série Divine.exe actuellement affichée, calculés
    # à partir des mêmes fichiers que `build_read_detail` (pas une note
    # figée décrivant un run passé — reste correct si le périmètre change).
    divine_reports = [
        (path, mode)
        for path, tool_key, _label, mode in _discover_read_reports(reports_dir)
        if tool_key == "divine"
    ]
    other_pak_counts = {
        mode
        for _path, tool_key, _label, mode in _discover_read_reports(reports_dir)
        if tool_key != "divine"
    }
    divine_modes_covered = {mode for _path, mode in divine_reports}
    divine_total = 0
    divine_errors = 0
    for path, _mode in divine_reports:
        data = _load(path)
        if data is None:
            continue
        paks = data.get("paks", {})
        divine_total += len(paks)
        divine_errors += sum(1 for v in paks.values() if v.get("error"))
    missing_modes = sorted(other_pak_counts - divine_modes_covered)

    note = (
        f"Divine.exe : {divine_total} .pak mesurés (mode per-file, un "
        f"lancement Wine par .pak), {divine_errors} en échec. "
        + (
            f"Dataset(s) non couverts par Divine.exe cette passe : "
            f"{', '.join(missing_modes)} (mode per-file trop lent à cette "
            f"échelle — plusieurs minutes déjà pour un seul dataset). "
            if missing_modes
            else ""
        )
        + "Le mode batch natif de Divine.exe/LSLib (un seul lancement Wine "
        "pour tout un dossier) plante systématiquement sur '-i pak' "
        "(CommandLineArguments.GetResourceFormatByString ne gère pas ce "
        "format — bug upstream LSLib, pas corrigeable côté script) : voir "
        "docs/pak-tools-benchmark/pak_tools_benchmark.md pour le détail. "
        "Les tentatives ci-dessous, en échec total, sont listées pour "
        "traçabilité, jamais mélangées aux chiffres de succès."
    )
    return {
        "note": note,
        "attempts": attempts,
    }


def build_create_edit(reports_dir: Path) -> dict[str, Any]:
    data = _load(reports_dir / "pak_bench_create_edit_report.json")
    results = (data or {}).get("results", [])
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in results:
        groups.setdefault((r["tool"], r["scenario"]), []).append(r)

    summary = []
    for (tool, scenario), items in sorted(groups.items()):
        ok = [i for i in items if not i.get("error")]
        times = [i["total_seconds"] for i in ok]
        summary.append(
            {
                "tool": tool,
                "scenario": scenario,
                "n": len(items),
                "n_errors": len(items) - len(ok),
                "median_seconds": round(median(times), 6),
                "min_seconds": round(min(times), 6) if times else 0.0,
                "max_seconds": round(max(times), 6) if times else 0.0,
                "verify_ok_rate": (sum(1 for i in ok if i.get("verify_ok")) / len(ok))
                if ok
                else 0.0,
            }
        )
    return {
        "generated_at": (data or {}).get("generated_at"),
        "summary": summary,
        "runs": [
            {
                "tool": r["tool"],
                "scenario": r["scenario"],
                "label": r["label"],
                "total_seconds": round(r["total_seconds"], 6),
                "file_count": r.get("file_count"),
                "verify_ok": r.get("verify_ok"),
                "error": _first_line(r.get("error")),
            }
            for r in results
        ],
    }


def build_dashboard_payload(reports_dir: Path) -> dict[str, Any]:
    detail_rows, summaries = build_read_detail(reports_dir)
    return {
        "read_summary": sorted(summaries.values(), key=lambda s: (s["mode"], s["tool"])),
        "read_detail": detail_rows,
        "divine_incomplete": build_divine_incomplete_status(reports_dir),
        "create_edit": build_create_edit(reports_dir),
    }


_DASHBOARD_SCRIPT_OPEN = '<script id="dashboard-data" type="application/json">'
_DASHBOARD_SCRIPT_CLOSE = "</script>"


def update_html_dashboard(html_path: Path, payload: dict[str, Any]) -> None:
    """Réinjecte `payload` dans le bloc `<script id="dashboard-data"
    type="application/json">...</script>` d'un dashboard HTML déjà publié
    (`docs/pak-tools-benchmark/dashboard.html`), sans toucher au reste de
    la page (structure, CSS, JS de rendu) — pas besoin de reconstruire le
    HTML à chaque run, seulement les données qu'il embarque.

    Suppose EXACTEMENT une occurrence du bloc, sur son propre
    marqueur d'ouverture `_DASHBOARD_SCRIPT_OPEN` suivi plus loin du
    marqueur de fermeture `_DASHBOARD_SCRIPT_CLOSE` — lève `ValueError` si
    la page n'a pas cette structure (page absente/jamais publiée avec ce
    gabarit, ou marqueurs renommés)."""
    html = html_path.read_text(encoding="utf-8")
    start = html.find(_DASHBOARD_SCRIPT_OPEN)
    if start == -1:
        raise ValueError(
            f"marqueur {_DASHBOARD_SCRIPT_OPEN!r} introuvable dans {html_path} — "
            "page absente ou pas au gabarit attendu"
        )
    data_start = start + len(_DASHBOARD_SCRIPT_OPEN)
    end = html.find(_DASHBOARD_SCRIPT_CLOSE, data_start)
    if end == -1:
        raise ValueError(f"marqueur de fermeture introuvable après l'ouverture dans {html_path}")

    new_json = json.dumps(payload, indent=2, ensure_ascii=False)
    new_html = html[:data_start] + new_json + html[end:]
    html_path.write_text(new_html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR / "dashboard_data.json")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument(
        "--html",
        type=Path,
        default=None,
        help="Si fourni, réinjecte aussi les données dans ce dashboard HTML déjà publié.",
    )
    args = parser.parse_args()

    payload = build_dashboard_payload(args.reports_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    size_kb = args.out.stat().st_size / 1024
    print(f"Wrote {args.out} ({size_kb:.1f} KiB)")
    print(f"read_summary rows: {len(payload['read_summary'])}")
    print(f"read_detail rows: {len(payload['read_detail'])}")
    print(f"create_edit summary rows: {len(payload['create_edit']['summary'])}")

    if args.html is not None:
        update_html_dashboard(args.html, payload)
        print(f"Dashboard HTML mis à jour : {args.html}")


if __name__ == "__main__":
    main()
