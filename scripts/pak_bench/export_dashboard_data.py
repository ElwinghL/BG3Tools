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

# (nom de fichier rapport, clé outil dans le dashboard, libellé, mode)
READ_REPORTS: list[tuple[str, str, str, str]] = [
    ("python_data_report.json", "python", "bg3pythonpaklib", "data"),
    ("python_mods_report.json", "python", "bg3pythonpaklib", "mods"),
    ("rust-native_data_report.json", "rust_native", "bg3rustpaklib (natif)", "data"),
    ("rust-native_mods_report.json", "rust_native", "bg3rustpaklib (natif)", "mods"),
    ("rust_data_report.json", "rust_pipeline", "bg3rustpaklib (pipeline PyO3)", "data"),
    ("rust_mods_report.json", "rust_pipeline", "bg3rustpaklib (pipeline PyO3)", "mods"),
    # divine_data_report.json : run Divine.exe le plus complet ET réussi au
    # moment de cet export (0 erreur) — écrase le fichier de façon
    # incrémentale (cf. `_write_report`), donc c'est un instantané d'un run
    # potentiellement encore en cours au moment de la génération ; supersede
    # divine_report.json (5 fichiers, sous-ensemble des mêmes noms) qui
    # reste la référence historique utilisée dans le rapport Markdown.
    ("divine_data_report.json", "divine", "Divine.exe", "data"),
]

# Rapports Divine.exe supplémentaires, chargés séparément car en échec total
# dans cette passe (documentés, pas mélangés aux séries de succès).
DIVINE_FAILED_REPORTS = ["divine_batch_report.json"]


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

    for fname, tool_key, label, mode in READ_REPORTS:
        data = _load(reports_dir / fname)
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
    """Documente les tentatives Divine.exe plus larges que le run à 5
    fichiers réussi (celui utilisé pour la série 'Divine.exe' du dashboard),
    toutes en échec total dans cette passe — cf. bug de flag `-u` invalide
    dans `scripts/compare_pak_reader.py::_run_divine_batch_tool`, encore en
    diagnostic au moment de cet export."""
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
    return {
        "note": (
            "La série 'Divine.exe' du dashboard vient de divine_data_report.json : "
            "run complet (mode per-file, un lancement Wine par .pak) sur les 48 "
            "fichiers du jeu de base, 42 réussis / 6 en échec — 3 timeouts "
            "(Materials.pak, Models.pak, SharedSounds.pak) et 3 crashs sans "
            "message exploitable (Gustav.pak, Textures.pak, VirtualTextures.pak, "
            "probablement OOM sur les plus gros fichiers/archives multi-parties). "
            "Les 205 .pak de mods n'ont PAS été passés par Divine.exe cette passe "
            "(mode per-file trop lent à l'échelle — ~15 min pour 48 fichiers déjà "
            "— et le mode batch natif de Divine.exe/LSLib plante systématiquement "
            "sur '-i pak', un bug upstream dans CommandLineArguments."
            "GetResourceFormatByString qui ne gère pas ce format, pas corrigeable "
            "côté script). Une tentative antérieure sur 328 fichiers "
            "(divine_batch_report.json, 2026-09-10) avait échoué à 100% sur un "
            "bug de flag -u distinct (corrigé depuis, cf. commit dans "
            "scripts/compare_pak_reader.py) — listée ici pour traçabilité, pas "
            "mélangée aux chiffres de succès."
        ),
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPORTS_DIR / "dashboard_data.json")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args()

    detail_rows, summaries = build_read_detail(args.reports_dir)
    payload = {
        "read_summary": sorted(summaries.values(), key=lambda s: (s["mode"], s["tool"])),
        "read_detail": detail_rows,
        "divine_incomplete": build_divine_incomplete_status(args.reports_dir),
        "create_edit": build_create_edit(args.reports_dir),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    size_kb = args.out.stat().st_size / 1024
    print(f"Wrote {args.out} ({size_kb:.1f} KiB)")
    print(f"read_summary rows: {len(payload['read_summary'])}")
    print(f"read_detail rows: {len(payload['read_detail'])}")
    print(f"create_edit summary rows: {len(payload['create_edit']['summary'])}")


if __name__ == "__main__":
    main()
