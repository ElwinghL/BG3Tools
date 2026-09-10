"""Planificateur de build classe/sous-classe niveau 1→20 (TODO P3.10).

Fonctionnalité volontairement **autonome** : indépendante du profil actif,
des mods installés et du reste de l'outil ModTools — voir `class_data.py`
pour les données et leurs limites documentées.

Ce module porte la logique pure (testable sans navigateur) :

- `LevelChoice` : le choix de classe/sous-classe fait à un niveau donné.
- `validate_build` : applique la règle de « progression continue vs nouveau
  choix » — on peut continuer indéfiniment la progression d'une classe déjà
  prise, mais une classe ne peut être sélectionnée comme *nouveau* choix
  qu'une seule fois sur l'ensemble du build (pas d'aller-retour entre deux
  classes déjà utilisées, cf TODO 10a/10d : « aucune classe doublon »).
- `build_report` : matérialise le build validé en une liste de gains par
  niveau (structure de données, réutilisée par `generate_html` pour la page
  exportable — voir la suite du TODO pour 10b/10c/10d).

La même règle est ré-implémentée côté JavaScript dans la page HTML générée
(`generate_html`), puisque la page doit fonctionner seule dans un
navigateur, sans dépendre de ce module Python une fois exportée. Ce module
Python reste la version canonique, testée dans `tests/test_class_builder.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bg3_mod_tui.class_data import CLASSES, get_level_features

MIN_LEVEL = 1
MAX_LEVEL = 20

DEFAULT_HTML_FILENAME = "build_classe_bg3.html"


@dataclass(frozen=True)
class LevelChoice:
    """Choix fait à un niveau donné du build."""

    level: int
    class_name: str
    subclass_name: str | None = None


def validate_build(choices: list[LevelChoice]) -> list[str]:
    """Valide un build niveau par niveau et retourne la liste des erreurs
    (vide si le build est valide). Règles appliquées :

    1. Les niveaux couverts doivent former la séquence continue 1..N (pas de
       trou, pas de doublon de niveau) — N pouvant être inférieur à 20 pour
       un build en cours de construction.
    2. Classe inconnue (absente de `class_data.CLASSES`) → erreur.
    3. Sous-classe choisie avant le niveau de déblocage de la classe, ou
       sous-classe inconnue pour cette classe → erreur.
    4. Une fois une sous-classe choisie pour une classe, elle doit rester la
       même sur tous les niveaux ultérieurs de cette classe (on ne change
       pas de sous-classe en cours de route).
    5. Règle de « nouveau choix » : le passage d'un niveau à l'autre vers une
       classe différente de celle du niveau précédent est un *nouveau
       choix*. Une classe ne peut faire l'objet que d'un seul nouveau choix
       sur tout le build — une fois quittée pour une autre classe, elle ne
       peut plus être reprise (pas de doublon de classe, cf TODO 10a).
    """
    errors: list[str] = []
    if not choices:
        return errors

    by_level = {c.level: c for c in choices}
    levels = sorted(by_level)

    if len(by_level) != len(choices):
        errors.append("Niveaux en double dans le build (un seul choix par niveau).")

    expected_start = MIN_LEVEL
    if levels and levels[0] != expected_start:
        errors.append(f"Le build doit commencer au niveau {MIN_LEVEL}.")

    for expected, actual in zip(range(levels[0] if levels else MIN_LEVEL, MAX_LEVEL + 1), levels):
        if expected != actual:
            errors.append(f"Niveau {expected} manquant (séquence non continue).")
            break

    used_as_new_choice: set[str] = set()
    subclass_by_class: dict[str, str] = {}
    prev_class: str | None = None

    for level in levels:
        choice = by_level[level]
        info = CLASSES.get(choice.class_name)
        if info is None:
            errors.append(f"Niveau {level} : classe inconnue « {choice.class_name} ».")
            continue

        is_new_choice = choice.class_name != prev_class
        if is_new_choice:
            if choice.class_name in used_as_new_choice:
                errors.append(
                    f"Niveau {level} : la classe « {choice.class_name} » a déjà été "
                    "quittée plus tôt dans le build — impossible de la reprendre "
                    "comme nouveau choix (une classe ne peut être choisie qu'une "
                    "seule fois comme nouveau choix, la progression continue est "
                    "en revanche illimitée)."
                )
            used_as_new_choice.add(choice.class_name)

        if choice.subclass_name:
            if choice.subclass_name not in info["subclasses"]:
                errors.append(
                    f"Niveau {level} : sous-classe inconnue « {choice.subclass_name} » "
                    f"pour {choice.class_name}."
                )
            else:
                unlock = info["subclass_unlock_level"]
                if level < unlock:
                    errors.append(
                        f"Niveau {level} : sous-classe choisie avant le niveau de "
                        f"déblocage ({unlock}) pour {choice.class_name}."
                    )
                existing = subclass_by_class.get(choice.class_name)
                if existing is not None and existing != choice.subclass_name:
                    errors.append(
                        f"Niveau {level} : changement de sous-classe pour "
                        f"{choice.class_name} ({existing} → {choice.subclass_name}) — "
                        "la sous-classe est fixée une fois choisie."
                    )
                else:
                    subclass_by_class[choice.class_name] = choice.subclass_name

        prev_class = choice.class_name

    return errors


def build_report(choices: list[LevelChoice]) -> list[dict]:
    """Matérialise un build validé en une liste (une entrée par niveau
    trié) de : niveau, classe (interne + FR), sous-classe active à ce
    niveau le cas échéant, et gains affichés (`class_data.get_level_features`).
    N'effectue aucune validation — appeler `validate_build` avant si le
    build doit être garanti cohérent."""
    by_level = {c.level: c for c in choices}
    subclass_by_class: dict[str, str] = {}
    report: list[dict] = []

    for level in sorted(by_level):
        choice = by_level[level]
        info = CLASSES.get(choice.class_name, {})
        if choice.subclass_name:
            subclass_by_class[choice.class_name] = choice.subclass_name
        active_subclass = subclass_by_class.get(choice.class_name)

        report.append(
            {
                "level": level,
                "class_name": choice.class_name,
                "class_fr": info.get("fr", choice.class_name),
                "subclass_name": active_subclass,
                "subclass_fr": (
                    info.get("subclasses", {}).get(active_subclass, {}).get("fr")
                    if active_subclass
                    else None
                ),
                "features": get_level_features(choice.class_name, level, active_subclass),
            }
        )

    return report


def _serialize_class_data() -> dict:
    """`CLASSES` en JSON-safe (les `asi_levels` sont des `set()` en Python,
    non sérialisables tel quel) — injecté tel quel dans la page HTML générée
    pour que toute la logique de sélection tourne côté client, sans
    dépendre de ce module Python une fois le fichier exporté."""
    serializable: dict = {}
    for class_name, info in CLASSES.items():
        serializable[class_name] = {
            "fr": info["fr"],
            "subclass_unlock_level": info["subclass_unlock_level"],
            "asi_levels": sorted(info.get("asi_levels", set())),
            "features_by_level": {str(k): v for k, v in info["features_by_level"].items()},
            "subclasses": {
                sub_name: {
                    "fr": sub["fr"],
                    "features_by_level": {str(k): v for k, v in sub["features_by_level"].items()},
                }
                for sub_name, sub in info["subclasses"].items()
            },
        }
    return serializable


def generate_html() -> str:
    """Génère la page HTML autonome du planificateur de build (TODO
    P3/10b) : un unique fichier, CSS/JS inline, aucune dépendance externe
    requise pour la fonction principale (sélection niveau par niveau,
    règle de progression, gains par niveau). Toute la logique tourne côté
    client dans le navigateur — la page fonctionne indépendamment du
    profil actif, des mods installés, et sans que ModTools ou ce module
    Python ne tournent une fois le fichier exporté/partagé."""
    class_data_json = json.dumps(_serialize_class_data(), ensure_ascii=False, indent=2)
    return _HTML_TEMPLATE.replace("__CLASS_DATA_JSON__", class_data_json).replace(
        "__MIN_LEVEL__", str(MIN_LEVEL)
    ).replace("__MAX_LEVEL__", str(MAX_LEVEL))


def write_html(output_path: Path | str = DEFAULT_HTML_FILENAME) -> Path:
    """Écrit la page générée par `generate_html` sur disque et retourne le
    chemin résolu. N'écrase rien d'autre : un unique fichier `.html`,
    autonome, prêt à être sauvegardé/partagé (TODO 10b)."""
    path = Path(output_path)
    path.write_text(generate_html(), encoding="utf-8")
    return path


_HTML_TEMPLATE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Planificateur de build — BG3 ModTools</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #16181d;
    --panel: #1f232b;
    --border: #333844;
    --text: #e7e9ee;
    --muted: #9aa2b1;
    --accent: #7aa2f7;
    --error: #f7768e;
    --ok: #9ece6a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 16px;
    background: var(--bg);
    color: var(--text);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    line-height: 1.4;
  }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  p.subtitle { color: var(--muted); margin: 0 0 16px; }
  details.limits {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 16px;
    max-width: 900px;
  }
  details.limits summary { cursor: pointer; color: var(--accent); font-weight: 600; }
  details.limits ul { margin: 8px 0 0; padding-left: 20px; color: var(--muted); font-size: 0.9rem; }
  #errors {
    background: #3a1e26;
    border: 1px solid var(--error);
    color: var(--error);
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 16px;
    display: none;
    max-width: 900px;
  }
  #errors.visible { display: block; }
  #errors ul { margin: 4px 0 0; padding-left: 20px; }
  #status-ok {
    background: #1e3a26;
    border: 1px solid var(--ok);
    color: var(--ok);
    border-radius: 8px;
    padding: 8px 14px;
    margin-bottom: 16px;
    display: none;
    max-width: 900px;
  }
  #status-ok.visible { display: block; }
  .toolbar { margin-bottom: 16px; display: flex; gap: 8px; }
  button {
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 6px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 0.9rem;
  }
  button:hover { border-color: var(--accent); }
  table#levels {
    width: 100%;
    max-width: 1100px;
    border-collapse: collapse;
  }
  table#levels th, table#levels td {
    border-bottom: 1px solid var(--border);
    padding: 6px 8px;
    text-align: left;
    vertical-align: top;
    font-size: 0.9rem;
  }
  table#levels th { color: var(--muted); font-weight: 600; }
  select {
    background: var(--panel);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 4px 6px;
    min-width: 160px;
  }
  select:disabled { opacity: 0.5; }
  ul.gains { margin: 0; padding-left: 18px; }
  ul.gains li { color: var(--muted); }
  .row-new-choice { color: var(--accent); font-size: 0.8rem; }
  .row-continuation { color: var(--muted); font-size: 0.8rem; }
  section#mermaid-section { margin-top: 24px; max-width: 1100px; }
</style>
</head>
<body>
<h1>Planificateur de build — Baldur's Gate 3</h1>
<p class="subtitle">
  Page autonome (aucun serveur, aucun mod, aucun profil requis) — choisissez
  une classe (et une sous-classe une fois débloquée) pour chaque niveau de
  __MIN_LEVEL__ à __MAX_LEVEL__. Générée par ModTools (bg3_mod_tui/class_builder.py).
</p>

<details class="limits">
  <summary>Limites des données (à lire)</summary>
  <ul>
    <li>BG3 plafonne réellement au niveau 12 — cette page couvre 1→20 (portée 5e complète), les niveaux 13-20 sont donc en partie extrapolés.</li>
    <li>Les gains par niveau sont une approximation raisonnable, pas une source patch-exacte vérifiée en jeu ni en ligne (page générée hors-ligne).</li>
    <li>Les sous-classes listées correspondent aux sous-classes principales connues de BG3 ; certaines mentions « à vérifier/à confirmer » signalent un contenu ajouté tardivement, moins certain.</li>
    <li>Structure pensée pour être facilement corrigée : voir <code>bg3_mod_tui/class_data.py</code> dans le dépôt ModTools.</li>
  </ul>
</details>

<div class="toolbar">
  <button id="reset-btn" type="button">Réinitialiser le build</button>
</div>

<div id="errors"></div>
<div id="status-ok">Build valide — aucune règle de progression enfreinte.</div>

<table id="levels">
  <thead>
    <tr>
      <th>Niveau</th>
      <th>Classe</th>
      <th>Sous-classe</th>
      <th>Type de choix</th>
      <th>Gains à ce niveau</th>
    </tr>
  </thead>
  <tbody id="levels-body"></tbody>
</table>

<section id="mermaid-section">
  <h2>Graph de progression</h2>
  <p class="subtitle">(intégration Mermaid — voir TODO 10c)</p>
</section>

<script>
const CLASS_DATA = __CLASS_DATA_JSON__;
const MIN_LEVEL = __MIN_LEVEL__;
const MAX_LEVEL = __MAX_LEVEL__;
const GENERIC_FALLBACK = "Progression de classe (sorts, ressources ou capacités supplémentaires selon la classe — non détaillé)";

const build = {}; // level(int) -> { classId, subclassId }

function classIds() {
  return Object.keys(CLASS_DATA).sort((a, b) => CLASS_DATA[a].fr.localeCompare(CLASS_DATA[b].fr, "fr"));
}

function getFeatures(classId, level, subclassId) {
  const info = CLASS_DATA[classId];
  if (!info) return [GENERIC_FALLBACK];
  let feats = (info.features_by_level[String(level)] || []).slice();
  if (info.asi_levels.includes(level) && !feats.some((f) => f.indexOf("Amélioration") !== -1)) {
    feats.push("Amélioration de caractéristique (+2 ou +1/+1) ou Don");
  }
  if (subclassId) {
    const sub = info.subclasses[subclassId];
    if (sub) {
      if (level === info.subclass_unlock_level) {
        feats.push("Choix de sous-classe : " + sub.fr);
      }
      feats = feats.concat(sub.features_by_level[String(level)] || []);
    }
  }
  if (feats.length === 0) feats.push(GENERIC_FALLBACK);
  return feats;
}

function validateBuild() {
  const errors = [];
  const levels = Object.keys(build)
    .map(Number)
    .filter((lvl) => build[lvl] && build[lvl].classId)
    .sort((a, b) => a - b);

  const usedAsNewChoice = new Set();
  const subclassByClass = {};
  let prevClass = null;

  for (const level of levels) {
    const choice = build[level];
    const info = CLASS_DATA[choice.classId];
    if (!info) {
      errors.push("Niveau " + level + " : classe inconnue.");
      continue;
    }
    const isNewChoice = choice.classId !== prevClass;
    if (isNewChoice) {
      if (usedAsNewChoice.has(choice.classId)) {
        errors.push(
          "Niveau " + level + " : « " + info.fr + " » a déjà été quittée plus tôt dans " +
          "le build — impossible de la reprendre comme nouveau choix (progression " +
          "continue illimitée, mais un seul nouveau choix par classe)."
        );
      }
      usedAsNewChoice.add(choice.classId);
    }
    if (choice.subclassId) {
      const sub = info.subclasses[choice.subclassId];
      if (!sub) {
        errors.push("Niveau " + level + " : sous-classe inconnue.");
      } else {
        if (level < info.subclass_unlock_level) {
          errors.push(
            "Niveau " + level + " : sous-classe choisie avant le déblocage (niveau " +
            info.subclass_unlock_level + ") pour " + info.fr + "."
          );
        }
        const existing = subclassByClass[choice.classId];
        if (existing && existing !== choice.subclassId) {
          errors.push("Niveau " + level + " : changement de sous-classe non autorisé pour " + info.fr + ".");
        } else {
          subclassByClass[choice.classId] = choice.subclassId;
        }
      }
    }
    prevClass = choice.classId;
  }
  return errors;
}

function renderErrors(errors) {
  const box = document.getElementById("errors");
  const ok = document.getElementById("status-ok");
  if (errors.length === 0) {
    box.classList.remove("visible");
    box.innerHTML = "";
    ok.classList.add("visible");
  } else {
    ok.classList.remove("visible");
    box.classList.add("visible");
    box.innerHTML =
      "<strong>Build invalide :</strong><ul>" +
      errors.map((e) => "<li>" + e + "</li>").join("") +
      "</ul>";
  }
}

function renderLevelRow(level) {
  const tr = document.createElement("tr");
  tr.dataset.level = String(level);

  const levelTd = document.createElement("td");
  levelTd.textContent = level;
  tr.appendChild(levelTd);

  const classTd = document.createElement("td");
  const classSelect = document.createElement("select");
  classSelect.innerHTML =
    '<option value="">— aucune —</option>' +
    classIds().map((id) => '<option value="' + id + '">' + CLASS_DATA[id].fr + "</option>").join("");
  const current = build[level];
  if (current && current.classId) classSelect.value = current.classId;
  classSelect.addEventListener("change", () => {
    build[level] = { classId: classSelect.value || null, subclassId: null };
    renderAll();
  });
  classTd.appendChild(classSelect);
  tr.appendChild(classTd);

  const subclassTd = document.createElement("td");
  const choice = build[level];
  if (choice && choice.classId) {
    const info = CLASS_DATA[choice.classId];
    const subSelect = document.createElement("select");
    if (level < info.subclass_unlock_level) {
      subSelect.disabled = true;
      subSelect.innerHTML = '<option>débloquée niveau ' + info.subclass_unlock_level + "</option>";
    } else {
      subSelect.innerHTML =
        '<option value="">— aucune —</option>' +
        Object.keys(info.subclasses)
          .map((id) => '<option value="' + id + '">' + info.subclasses[id].fr + "</option>")
          .join("");
      if (choice.subclassId) subSelect.value = choice.subclassId;
      subSelect.addEventListener("change", () => {
        build[level].subclassId = subSelect.value || null;
        renderAll();
      });
    }
    subclassTd.appendChild(subSelect);
  }
  tr.appendChild(subclassTd);

  const typeTd = document.createElement("td");
  tr.appendChild(typeTd);

  const gainsTd = document.createElement("td");
  if (choice && choice.classId) {
    const ul = document.createElement("ul");
    ul.className = "gains";
    getFeatures(choice.classId, level, choice.subclassId).forEach((f) => {
      const li = document.createElement("li");
      li.textContent = f;
      ul.appendChild(li);
    });
    gainsTd.appendChild(ul);
  }
  tr.appendChild(gainsTd);

  return tr;
}

function renderAll() {
  const tbody = document.getElementById("levels-body");
  tbody.innerHTML = "";
  for (let level = MIN_LEVEL; level <= MAX_LEVEL; level++) {
    tbody.appendChild(renderLevelRow(level));
  }
  renderErrors(validateBuild());
}

document.getElementById("reset-btn").addEventListener("click", () => {
  for (const key of Object.keys(build)) delete build[key];
  renderAll();
});

renderAll();
</script>
</body>
</html>
"""
