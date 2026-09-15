"""Génère des arborescences source synthétiques (pas de vrais .pak BG3
requis) pour exercer/valider le harness de bout en bout — tailles et
nombre de fichiers variés, contenu pseudo-aléatoire mais déterministe
(seedé) pour des runs reproductibles. Voir la note de méthodologie dans
`docs/superpowers/specs/2026-09-15-pak-tools-benchmark-design.md` :
cette passe n'utilise pas de vrais .pak du jeu, uniquement des fixtures
synthétiques, sur décision explicite de l'utilisateur.
"""

from __future__ import annotations

import random
from pathlib import Path

# Profils délibérément variés : peu de gros fichiers (texture-like) vs
# beaucoup de petits fichiers (localisation/scripts-like) vs mix.
PROFILES: dict[str, list[tuple[int, int]]] = {
    # (nombre_de_fichiers, taille_octets_max) par groupe
    "small-many": [(200, 2_000)],
    "large-few": [(5, 2_000_000)],
    "mixed": [(50, 5_000), (10, 200_000), (2, 1_000_000)],
}


def generate_source_tree(root: Path, profile: str = "mixed", *, seed: int = 0) -> int:
    """Crée `root` (nettoyé s'il existe déjà) rempli selon `profile` (voir
    `PROFILES`). Retourne le nombre de fichiers créés. Inclut toujours un
    `Mods/BenchFixture/meta.lsx` minimal pour rester représentatif d'un
    vrai mod BG3 (structure attendue par Divine.exe `create-package`)."""
    import shutil

    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    rng = random.Random(seed)
    count = 0

    meta_dir = root / "Mods" / "BenchFixture"
    meta_dir.mkdir(parents=True)
    (meta_dir / "meta.lsx").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<save><version major="4" minor="0" revision="0" build="0"/><region id="Config">'
        '<node id="root"><children><node id="ModuleInfo">'
        '<attribute id="UUID" type="FixedString" value="00000000-0000-0000-0000-000000000000"/>'
        '<attribute id="Name" type="LSString" value="BenchFixture"/>'
        "</node></children></node></region></save>\n",
        encoding="utf-8",
    )
    count += 1

    groups = PROFILES.get(profile, PROFILES["mixed"])
    for group_index, (n_files, max_size) in enumerate(groups):
        group_dir = root / "Generated" / f"group{group_index}"
        group_dir.mkdir(parents=True, exist_ok=True)
        for i in range(n_files):
            size = rng.randint(16, max(16, max_size))
            data = rng.randbytes(size)
            (group_dir / f"file_{i:05d}.bin").write_bytes(data)
            count += 1

    return count


def generate_overlay_tree(
    source_root: Path, overlay_root: Path, *, fraction: float = 0.1, seed: int = 1
) -> int:
    """Construit un dossier d'overlay pour le scénario édition : copie
    d'un sous-ensemble (`fraction`) des fichiers de `source_root` avec un
    contenu modifié (même chemin relatif, octets différents) — c'est ce
    dossier qui est appliqué par-dessus l'extraction lors de l'édition.
    Retourne le nombre de fichiers d'overlay créés."""
    import shutil

    if overlay_root.exists():
        shutil.rmtree(overlay_root)
    overlay_root.mkdir(parents=True)

    rng = random.Random(seed)
    all_files = [p for p in source_root.rglob("*") if p.is_file()]
    sample_size = max(1, int(len(all_files) * fraction))
    chosen = rng.sample(all_files, min(sample_size, len(all_files)))

    for src in chosen:
        rel = src.relative_to(source_root)
        dest = overlay_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(rng.randbytes(max(16, src.stat().st_size)))

    return len(chosen)
