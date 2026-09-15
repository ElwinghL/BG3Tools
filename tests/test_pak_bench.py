"""Tests de `scripts/pak_bench` : logique pure (pas de subprocess, pas de
vrai .pak/Divine.exe/Wine) — échantillonnage stratifié, écriture/lecture de
rapport JSON, agrégation des résultats création/édition et génération du
Markdown du rapport. Les binaires natifs (`native_timing`) et Divine.exe ne
sont pas invoqués ici : voir la note de méthodologie du spec (aucune
mesure réelle testée en CI, seulement le pipeline de mesure lui-même)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.pak_bench.common import (
    PakRecord,
    ScenarioResult,
    _pick_sample_names,
    _write_report,
    load_merged_tool_report,
    load_scenario_report,
    median,
    write_scenario_report,
)
from scripts.pak_bench.export_dashboard_data import _discover_read_reports, update_html_dashboard
from scripts.pak_bench.report import (
    render_markdown,
    summarize_create_edit,
    summarize_read_report,
)
from scripts.pak_bench.synthetic import generate_overlay_tree, generate_source_tree


def test_pick_sample_names_includes_meta_and_stays_under_cap():
    entries = {f"file_{i}.bin": {"size": i, "compression": i % 3} for i in range(50)}
    entries["Mods/X/meta.lsx"] = {"size": 10, "compression": 0}
    sample = _pick_sample_names(entries, cap=10)
    assert len(sample) == 10
    assert "Mods/X/meta.lsx" in sample


def test_pick_sample_names_returns_all_when_under_cap():
    entries = {f"f{i}": {"size": 1, "compression": 0} for i in range(5)}
    assert sorted(_pick_sample_names(entries, cap=10)) == sorted(entries)


def test_median():
    assert median([]) == 0.0
    assert median([2.0]) == 2.0
    assert median([1.0, 3.0]) == 2.0
    assert median([1.0, 2.0, 3.0]) == 2.0


def test_write_report_roundtrip(tmp_path):
    out = tmp_path / "report.json"
    records = {"a.pak": PakRecord(file="a.pak", index_or_extract_seconds=1.5)}
    _write_report(out, "python", 60, records, extra={"note": "x"})
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["tool"] == "python"
    assert payload["note"] == "x"
    assert payload["paks"]["a.pak"]["index_or_extract_seconds"] == 1.5


def test_scenario_report_roundtrip(tmp_path):
    out = tmp_path / "ce_report.json"
    results = [
        ScenarioResult(
            tool="bg3rustpaklib",
            scenario="create-single",
            label="x.pak",
            total_seconds=0.1,
            verify_ok=True,
        ),
        ScenarioResult(
            tool="bg3rustpaklib",
            scenario="create-single",
            label="y.pak",
            total_seconds=0.3,
            error="boom",
        ),
    ]
    write_scenario_report(out, results)
    loaded = load_scenario_report(out)
    assert len(loaded) == 2
    assert loaded[0]["label"] == "x.pak"
    assert loaded[1]["error"] == "boom"


def test_load_scenario_report_missing_file(tmp_path):
    assert load_scenario_report(tmp_path / "missing.json") == []


def test_summarize_read_report_totals_and_errors():
    report = {
        "paks": {
            "a.pak": {"index_or_extract_seconds": 1.0, "content_seconds": 0.5, "error": None},
            "b.pak": {"index_or_extract_seconds": 2.0, "content_seconds": 0.25, "error": "boom"},
        }
    }
    s = summarize_read_report(report)
    assert s["index_seconds"] == 3.0
    assert s["content_seconds"] == 0.75
    assert s["total_seconds"] == 3.75
    assert s["pak_count"] == 2
    assert s["errors"] == 1


def test_summarize_create_edit_median_and_verify_rate():
    results = [
        {
            "tool": "bg3rustpaklib",
            "scenario": "create-single",
            "total_seconds": 0.1,
            "verify_ok": True,
            "error": None,
        },
        {
            "tool": "bg3rustpaklib",
            "scenario": "create-single",
            "total_seconds": 0.3,
            "verify_ok": True,
            "error": None,
        },
        {
            "tool": "bg3rustpaklib",
            "scenario": "create-single",
            "total_seconds": 0.0,
            "verify_ok": False,
            "error": "boom",
        },
    ]
    summary = summarize_create_edit(results)
    key = ("bg3rustpaklib", "create-single")
    assert summary[key]["n"] == 3
    assert summary[key]["n_errors"] == 1
    assert summary[key]["median_seconds"] == 0.2  # median of [0.1, 0.3] (errored run excluded)
    assert summary[key]["verify_ok_rate"] == 1.0


def test_render_markdown_handles_empty_inputs():
    md = render_markdown({}, [], capability_matrix="| a | b |\n|---|---|\n")
    assert "Aucun rapport de lecture" in md
    assert "Aucun résultat création/édition" in md
    assert "| a | b |" in md


def test_render_markdown_with_data():
    read_reports = {
        "python": {
            "paks": {
                "a.pak": {"index_or_extract_seconds": 1.0, "content_seconds": 0.1, "error": None}
            }
        },
    }
    results = [
        {
            "tool": "bg3rustpaklib",
            "scenario": "create-single",
            "total_seconds": 0.05,
            "verify_ok": True,
            "error": None,
        },
    ]
    md = render_markdown(read_reports, results, capability_matrix="matrix")
    assert "bg3pythonpaklib" in md
    assert "bg3rustpaklib" in md
    assert "create-single" in md


def test_generate_source_tree_creates_meta_and_files(tmp_path):
    root = tmp_path / "src"
    count = generate_source_tree(root, profile="small-many", seed=1)
    assert count > 1
    assert (root / "Mods" / "BenchFixture" / "meta.lsx").is_file()
    files = [p for p in root.rglob("*") if p.is_file()]
    assert len(files) == count


def test_generate_source_tree_deterministic_with_seed(tmp_path):
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    generate_source_tree(root_a, profile="small-many", seed=7)
    generate_source_tree(root_b, profile="small-many", seed=7)
    files_a = sorted(p.read_bytes() for p in root_a.rglob("*") if p.is_file())
    files_b = sorted(p.read_bytes() for p in root_b.rglob("*") if p.is_file())
    assert files_a == files_b


def test_generate_overlay_tree_subset_of_source(tmp_path):
    root = tmp_path / "src"
    generate_source_tree(root, profile="small-many", seed=3)
    overlay = tmp_path / "overlay"
    n = generate_overlay_tree(root, overlay, fraction=0.2, seed=1)
    overlay_files = [p for p in overlay.rglob("*") if p.is_file()]
    assert len(overlay_files) == n
    for f in overlay_files:
        rel = f.relative_to(overlay)
        assert (root / rel).is_file()


# -- automatisation du dashboard (regression du bug du 2026-09-15) ----------


def _write_read_report(path: Path, paks: dict) -> None:
    path.write_text(
        json.dumps({"tool": "x", "generated_at": "t", "sample_cap": 60, "paks": paks}),
        encoding="utf-8",
    )


def test_load_merged_tool_report_combines_canonical_and_split_files(tmp_path):
    _write_read_report(tmp_path / "rust-native_data_report.json", {"A.pak": {"error": None}})
    _write_read_report(tmp_path / "rust-native_mods_report.json", {"B.pak": {"error": "x"}})
    merged = load_merged_tool_report("rust-native", tmp_path)
    assert merged is not None
    assert set(merged["paks"]) == {"A.pak", "B.pak"}


def test_load_merged_tool_report_missing_tool_returns_none(tmp_path):
    assert load_merged_tool_report("divine", tmp_path) is None


def test_discover_read_reports_ignores_unrelated_and_failed_files(tmp_path):
    _write_read_report(tmp_path / "rust-native_data_report.json", {})
    _write_read_report(tmp_path / "rust_mods_report.json", {})
    _write_read_report(tmp_path / "divine_batch_FAILED_attempt.json", {})
    (tmp_path / "coverage.json").write_text("{}", encoding="utf-8")
    (tmp_path / "ruff_report.json").write_text("{}", encoding="utf-8")

    found = _discover_read_reports(tmp_path)
    keys = {(tool, mode) for _path, tool, _label, mode in found}
    assert ("rust_native", "data") in keys
    assert ("rust_pipeline", "mods") in keys
    assert not any(path.name == "divine_batch_FAILED_attempt.json" for path, *_ in found)
    assert len(found) == 2  # ni coverage.json ni ruff_report.json (préfixe outil inconnu)


def test_update_html_dashboard_replaces_only_data_block(tmp_path):
    html = (
        "<html><body>keep-me"
        '<script id="dashboard-data" type="application/json">{"old": true}</script>'
        "keep-me-too</body></html>"
    )
    path = tmp_path / "dashboard.html"
    path.write_text(html, encoding="utf-8")

    update_html_dashboard(path, {"new": [1, 2, 3]})

    result = path.read_text(encoding="utf-8")
    assert "keep-me" in result
    assert "keep-me-too" in result
    assert '"old": true' not in result
    assert '"new"' in result
    payload = json.loads(
        result.split('<script id="dashboard-data" type="application/json">')[1].split("</script>")[
            0
        ]
    )
    assert payload == {"new": [1, 2, 3]}


def test_update_html_dashboard_missing_marker_raises(tmp_path):
    path = tmp_path / "dashboard.html"
    path.write_text("<html><body>no data block here</body></html>", encoding="utf-8")
    try:
        update_html_dashboard(path, {})
        raise AssertionError("devrait lever ValueError")
    except ValueError:
        pass
