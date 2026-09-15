"""Logique commune extraite de `scripts/compare_pak_reader.py` : le
dataclass `PakRecord`, le hachage de contenu, l'écriture de rapport JSON
et l'échantillonnage stratifié des entrées à hasher. Partagée par le
lecteur (`compare_pak_reader.py`, rétro-compatible) et par les nouveaux
scénarios création/édition/batch/rapport (`pak_bench_cli.py`,
`pak_bench/create_edit.py`, `pak_bench/report.py`).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


@dataclass
class PakRecord:
    file: str
    error: str | None = None
    identity: tuple[str, str] | None = None
    entries: dict[str, dict[str, int]] = field(default_factory=dict)  # name -> {size, compression}
    index_or_extract_seconds: float = 0.0
    content_hashes: dict[str, str] = field(default_factory=dict)
    content_errors: dict[str, str] = field(
        default_factory=dict
    )  # nom d'entrée -> erreur (n'interrompt pas le run)
    content_seconds: float = 0.0


@dataclass
class ScenarioResult:
    """Résultat d'un scénario création/édition/batch pour UN outil — pas
    un `PakRecord` (pensé pour la lecture) : ici on chronomètre des étapes
    nommées (`create`/`extract`+`modify`+`repack`) plutôt que index vs
    contenu, et on garde un statut de vérification round-trip explicite."""

    tool: str
    scenario: str  # "create-single", "create-batch", "edit-single", "edit-batch"
    label: str  # nom du .pak / du lot
    seconds: dict[str, float] = field(default_factory=dict)  # étape -> temps
    total_seconds: float = 0.0
    verify_ok: bool | None = None
    file_count: int = 0
    error: str | None = None


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
    lieu de rien du tout."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "tool": tool,
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_cap": sample_cap,
        **(extra or {}),
        "paks": {name: asdict(record) for name, record in records.items()},
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_scenario_report(out_path: Path, results: list[ScenarioResult]) -> None:
    """Équivalent de `_write_report` pour les scénarios création/édition :
    un rapport JSON simple, une liste de `ScenarioResult` sérialisés."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "results": [asdict(r) for r in results],
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_scenario_report(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("results", [])


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0
