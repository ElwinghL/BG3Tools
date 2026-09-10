"""Planificateur de build classe/sous-classe niveau 1→12 (TODO P3.10).

Fonctionnalité volontairement **autonome** : indépendante du profil actif,
des mods installés et du reste de l'outil ModTools — voir `class_data.py`
pour les données et leurs limites documentées.

Ce module porte la logique pure (testable sans navigateur) :

- `LevelChoice` : le choix de classe/sous-classe fait à un niveau donné.
- `validate_build` : vérifie la séquence de niveaux (continue, sans trou ni
  doublon) et la cohérence des sous-classes (pas choisie avant son niveau
  de déblocage *dans sa classe*, jamais changée une fois fixée). Aucune
  restriction sur l'ordre des classes : en 5e réelle, le multiclassage
  permet d'alterner librement entre classes déjà commencées à chaque
  niveau (confirmé explicitement par Elwingh après une première version qui
  imposait à tort « une classe fermée une fois quittée » — pas une vraie
  règle 5e, retirée).
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
MAX_LEVEL = 12  # plafond réel BG3 vanilla — voir class_data.py pour la portée

DEFAULT_HTML_FILENAME = "build_classe_bg3.html"


@dataclass(frozen=True)
class LevelChoice:
    """Choix fait à un niveau donné du build."""

    level: int
    class_name: str
    subclass_name: str | None = None


def _level_in_class(by_level: dict[int, LevelChoice], level: int, class_name: str) -> int:
    """Niveau *au sein de* `class_name` atteint en incluant `level` — les
    règles 5e de multiclassage (`features_by_level`/`asi_levels`/
    `subclass_unlock_level` dans `class_data.py`) sont définies par rapport
    au niveau DANS la classe, pas au niveau total du personnage (ex: Barbare
    1 / Roublard 2 a les gains de "Roublard niveau 2", pas "niveau 3")."""
    return sum(1 for lvl, choice in by_level.items() if lvl <= level and choice.class_name == class_name)


def validate_build(choices: list[LevelChoice]) -> list[str]:
    """Valide un build niveau par niveau et retourne la liste des erreurs
    (vide si le build est valide). Règles appliquées :

    1. Les niveaux couverts doivent former la séquence continue 1..N (pas de
       trou, pas de doublon de niveau) — N pouvant être inférieur à
       `MAX_LEVEL` pour un build en cours de construction.
    2. Classe inconnue (absente de `class_data.CLASSES`) → erreur.
    3. Sous-classe choisie avant le niveau de déblocage *dans sa classe*, ou
       sous-classe inconnue pour cette classe → erreur.
    4. Une fois une sous-classe choisie pour une classe, elle doit rester la
       même sur tous les niveaux ultérieurs de cette classe (on ne change
       pas de sous-classe en cours de route).

    Aucune restriction sur l'ordre des classes entre elles : on peut alterner
    librement entre classes déjà commencées à chaque niveau (multiclassage
    5e standard, pas de notion de classe "fermée" une fois quittée).
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

    subclass_by_class: dict[str, str] = {}

    for level in levels:
        choice = by_level[level]
        info = CLASSES.get(choice.class_name)
        if info is None:
            errors.append(f"Niveau {level} : classe inconnue « {choice.class_name} ».")
            continue

        if choice.subclass_name:
            if choice.subclass_name not in info["subclasses"]:
                errors.append(
                    f"Niveau {level} : sous-classe inconnue « {choice.subclass_name} » "
                    f"pour {choice.class_name}."
                )
            else:
                unlock = info["subclass_unlock_level"]
                level_in_class = _level_in_class(by_level, level, choice.class_name)
                if level_in_class < unlock:
                    errors.append(
                        f"Niveau {level} : sous-classe choisie avant le niveau de "
                        f"déblocage ({unlock}e niveau de {choice.class_name}, "
                        f"actuellement {level_in_class}e) pour {choice.class_name}."
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
        level_in_class = _level_in_class(by_level, level, choice.class_name)

        report.append(
            {
                "level": level,
                "level_in_class": level_in_class,
                "class_name": choice.class_name,
                "class_fr": info.get("fr", choice.class_name),
                "subclass_name": active_subclass,
                "subclass_fr": (
                    info.get("subclasses", {}).get(active_subclass, {}).get("fr")
                    if active_subclass
                    else None
                ),
                "features": get_level_features(choice.class_name, level_in_class, active_subclass),
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


_HTML_TEMPLATE = r"""<!doctype html>
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
    --confirmed-bg: #101216;
    --choice-bg: #4b4f58;
    --choice-bg-hover: #656a75;
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
  .toolbar { margin-bottom: 20px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
  .toolbar .buttons { display: flex; gap: 8px; }
  .toolbar label { color: var(--muted); font-size: 0.85rem; display: flex; align-items: center; gap: 6px; cursor: pointer; }
  button {
    background: var(--panel);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 6px;
    padding: 6px 12px;
    cursor: pointer;
    font-size: 0.9rem;
  }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: 0.4; cursor: default; }
  #class-summary { max-width: 1100px; }
  #build-status { color: var(--accent); margin: 0 0 20px; display: none; }
  #build-status.visible { display: block; }

  #graph-wrapper { position: relative; }
  #connector-svg { position: absolute; top: 0; left: 0; overflow: visible; pointer-events: none; }
  #build-graph { position: relative; z-index: 1; display: flex; flex-direction: column; align-items: center; }
  .connector { width: 2px; height: 26px; background: var(--border); }
  .node {
    border-radius: 10px;
    padding: 8px 14px;
    font-size: 0.82rem;
    text-align: center;
    min-width: 110px;
    max-width: 220px;
  }
  .node.confirmed {
    background: var(--confirmed-bg);
    color: var(--text);
    border: 1px solid #000;
  }
  .node-caption {
    margin-top: 4px;
    font-size: 0.72rem;
    color: var(--muted);
  }
  #choices-heading {
    position: relative;
    z-index: 1;
    color: var(--muted);
    font-size: 0.8rem;
    margin: 12px 0 0;
    text-align: center;
  }
  #choices-area {
    position: relative;
    z-index: 1;
    height: 360px;
  }
  .node.choice {
    position: absolute;
    top: 0;
    left: 0;
    background: var(--choice-bg);
    color: var(--text);
    border: 1px solid #5a5f69;
    cursor: pointer;
    transition: background 0.12s;
    will-change: transform;
  }
  .node.choice:hover { background: var(--choice-bg-hover); }
</style>
</head>
<body>
<h1>Planificateur de build — Baldur's Gate 3</h1>
<p class="subtitle">
  Page autonome (aucun serveur, aucun mod, aucun profil requis) — construisez
  votre build niveau après niveau (__MIN_LEVEL__ à __MAX_LEVEL__, plafond
  vanilla BG3) en cliquant les choix disponibles sous la chaîne actuelle.
  Générée par ModTools (bg3_mod_tui/class_builder.py).
</p>

<div class="toolbar">
  <div class="buttons">
    <button id="undo-btn" type="button">Annuler le dernier choix</button>
    <button id="reset-btn" type="button">Réinitialiser le build</button>
  </div>
  <label><input type="checkbox" id="compact-toggle"> Affichage compact (masquer le détail des gains)</label>
</div>

<div id="class-summary" class="subtitle"></div>
<p id="build-status">Build complet — niveau __MAX_LEVEL__ atteint.</p>

<div id="graph-wrapper">
  <svg id="connector-svg"></svg>
  <div id="build-graph"></div>
  <p id="choices-heading"></p>
  <div id="choices-area"></div>
</div>

<script>
const CLASS_DATA = __CLASS_DATA_JSON__;
const MIN_LEVEL = __MIN_LEVEL__;
const MAX_LEVEL = __MAX_LEVEL__;
const GENERIC_FALLBACK = "Progression de classe (sorts, ressources ou capacités supplémentaires selon la classe — non détaillé)";

// État : une entrée par niveau du personnage déjà confirmé, dans l'ordre
// (state[0] = niveau 1, state[state.length-1] = dernier niveau confirmé).
// Construit uniquement en cliquant un choix proposé par computeNextOptions
// -> impossible de construire un build qui enfreint la règle de
// progression (continuation illimitée d'une classe active, un seul
// nouveau choix par classe sur tout le build).
const state = [];

function classIds() {
  return Object.keys(CLASS_DATA).sort((a, b) => CLASS_DATA[a].fr.localeCompare(CLASS_DATA[b].fr, "fr"));
}

// Niveau *dans* classId en ne comptant que state[0..upToIndex-1] (miroir de
// `class_builder._level_in_class` côté Python).
function levelInClass(upToIndex, classId) {
  let count = 0;
  for (let i = 0; i < upToIndex; i++) {
    if (state[i].classId === classId) count++;
  }
  return count;
}

function usedClassesSet() {
  return new Set(state.map((choice) => choice.classId));
}

function getFeatures(classId, levelInClassValue, subclassId) {
  const info = CLASS_DATA[classId];
  if (!info) return [GENERIC_FALLBACK];
  let feats = (info.features_by_level[String(levelInClassValue)] || []).slice();
  if (info.asi_levels.includes(levelInClassValue) && !feats.some((f) => f.indexOf("Amélioration") !== -1)) {
    feats.push("Amélioration de caractéristique (+2 ou +1/+1) ou Don");
  }
  if (subclassId) {
    const sub = info.subclasses[subclassId];
    if (sub) {
      if (levelInClassValue === info.subclass_unlock_level) {
        feats.push("Choix de sous-classe : " + sub.fr);
      }
      feats = feats.concat(sub.features_by_level[String(levelInClassValue)] || []);
    }
  }
  if (feats.length === 0) feats.push(GENERIC_FALLBACK);
  return feats;
}

// Choix disponibles pour le PROCHAIN niveau, calculés depuis `state` :
// continuer N'IMPORTE QUELLE classe déjà commencée (avec fork en un choix
// par sous-classe si ce niveau est justement celui du déblocage), ou
// multiclasser vers une classe pas encore utilisée (même fork si sa
// sous-classe se débloque dès son niveau 1 — Clerc/Ensorceleur/Occultiste).
// Pas de notion de classe "fermée" : le multiclassage 5e permet d'alterner
// librement entre classes déjà commencées, niveau après niveau.
function computeNextOptions() {
  if (state.length >= MAX_LEVEL) return [];
  const options = [];
  const used = usedClassesSet();

  for (const classId of classIds()) {
    if (!used.has(classId)) continue;
    const info = CLASS_DATA[classId];
    const nextLevel = levelInClass(state.length, classId) + 1;
    const alreadyHasSubclass = state.some((c) => c.classId === classId && c.subclassId);
    if (nextLevel === info.subclass_unlock_level && !alreadyHasSubclass) {
      for (const subId of Object.keys(info.subclasses)) {
        options.push({
          classId,
          subclassId: subId,
          label: "Continuer " + info.fr + " " + nextLevel + " (" + info.subclasses[subId].fr + ")",
        });
      }
    } else {
      options.push({ classId, subclassId: null, label: "Continuer " + info.fr + " " + nextLevel });
    }
  }

  for (const classId of classIds()) {
    if (used.has(classId)) continue;
    const info = CLASS_DATA[classId];
    const verb = state.length === 0 ? "Commencer" : "Multiclasser";
    if (info.subclass_unlock_level === 1) {
      for (const subId of Object.keys(info.subclasses)) {
        options.push({
          classId,
          subclassId: subId,
          label: verb + " : " + info.fr + " (" + info.subclasses[subId].fr + ")",
        });
      }
    } else {
      options.push({ classId, subclassId: null, label: verb + " : " + info.fr + " 1" });
    }
  }

  return options;
}

function renderClassSummary() {
  const el = document.getElementById("class-summary");
  const used = usedClassesSet();
  if (used.size === 0) {
    el.textContent = "Aucune classe choisie pour l'instant.";
    return;
  }
  const parts = Array.from(used).map((id) => CLASS_DATA[id].fr + " " + levelInClass(state.length, id));
  el.textContent = "Classes en cours dans ce build : " + parts.join(", ") + ".";
}

let compactMode = false;

function makeConfirmedNode(choice, index) {
  const info = CLASS_DATA[choice.classId];
  const lvl = levelInClass(index + 1, choice.classId);
  const label = info.fr + " " + lvl + (choice.subclassId ? " (" + info.subclasses[choice.subclassId].fr + ")" : "");
  const feats = getFeatures(choice.classId, lvl, choice.subclassId);

  const node = document.createElement("div");
  node.className = "node confirmed";
  node.title = feats.join("\n");

  const title = document.createElement("div");
  title.textContent = label;
  node.appendChild(title);

  if (!compactMode) {
    const caption = document.createElement("div");
    caption.className = "node-caption";
    caption.textContent = feats.join(", ");
    node.appendChild(caption);
  }

  return node;
}

// Simulation à forces façon graphe orienté force (ressort + répulsion,
// style Fruchterman-Reingold simplifié) — demandé explicitement par
// Elwingh ("graph pieuvre") pour remplacer la grille rigide précédente :
// chaque choix "flotte" autour de l'ancre (le dernier nœud confirmé),
// repoussé par ses voisins pour ne jamais se chevaucher, avec un
// déplacement fluide animé plutôt qu'un repositionnement instantané.
const SPRING_K = 0.02;
const REPULSION = 2600;
const DAMPING = 0.82;
const COLLISION_PADDING = 10;

let physicsNodes = []; // { x, y, vx, vy, el }
let animationFrameId = null;
let restLength = 150; // recalculé par render() selon le nombre de choix

function computeAnchor(wrapperRect) {
  const confirmedNodes = document.querySelectorAll("#build-graph .node.confirmed");
  if (confirmedNodes.length > 0) {
    const lastRect = confirmedNodes[confirmedNodes.length - 1].getBoundingClientRect();
    return {
      x: lastRect.left + lastRect.width / 2 - wrapperRect.left,
      y: lastRect.bottom - wrapperRect.top + 20,
    };
  }
  const area = document.getElementById("choices-area");
  return { x: area.getBoundingClientRect().width / 2, y: 30 };
}

function stepPhysics(anchor, width, height) {
  for (const n of physicsNodes) {
    const dxA = n.x - anchor.x;
    const dyA = n.y - anchor.y;
    const distA = Math.max(Math.hypot(dxA, dyA), 1);
    const springForce = (restLength - distA) * SPRING_K;
    let fx = (dxA / distA) * springForce;
    let fy = (dyA / distA) * springForce;

    for (const other of physicsNodes) {
      if (other === n) continue;
      const dx = n.x - other.x;
      const dy = n.y - other.y;
      const distSq = Math.max(dx * dx + dy * dy, 1);
      const force = REPULSION / distSq;
      const dist = Math.sqrt(distSq);
      fx += (dx / dist) * force;
      fy += (dy / dist) * force;
    }

    n.vx = (n.vx + fx) * DAMPING;
    n.vy = (n.vy + fy) * DAMPING;
    n.x += n.vx;
    n.y += n.vy;

    // Les tentacules s'étalent SOUS l'ancre (jamais par-dessus la chaîne
    // confirmée) et restent dans la zone visible — pas de scroll requis.
    if (n.y < anchor.y) {
      n.y = anchor.y;
      n.vy = Math.abs(n.vy) * 0.3;
    }
    n.x = Math.min(Math.max(n.x, 60), Math.max(width - 60, 60));
    n.y = Math.min(n.y, height - 30);
  }
}

// Passe de résolution de collision (AABB, plusieurs itérations) en plus
// des forces ressort/répulsion : la répulsion seule (centre à centre) ne
// tient pas compte de la largeur/hauteur réelle de chaque boîte (variable
// selon la longueur du libellé), donc deux nœuds peuvent rester en
// équilibre de force tout en ayant leurs rectangles qui se chevauchent —
// cette passe garantit l'absence de chevauchement quel que soit le nombre
// de choix, en poussant explicitement les boîtes qui se recouvrent le long
// de leur axe de moindre chevauchement (séparation douce, pas un saut).
function resolveCollisions(anchor, width, height) {
  for (let iteration = 0; iteration < 3; iteration++) {
    for (let i = 0; i < physicsNodes.length; i++) {
      for (let j = i + 1; j < physicsNodes.length; j++) {
        const a = physicsNodes[i];
        const b = physicsNodes[j];
        const aHalfW = a.el.offsetWidth / 2 + COLLISION_PADDING;
        const aHalfH = a.el.offsetHeight / 2 + COLLISION_PADDING;
        const bHalfW = b.el.offsetWidth / 2 + COLLISION_PADDING;
        const bHalfH = b.el.offsetHeight / 2 + COLLISION_PADDING;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const overlapX = aHalfW + bHalfW - Math.abs(dx);
        const overlapY = aHalfH + bHalfH - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;

        if (overlapX < overlapY) {
          const push = (overlapX / 2) * (dx < 0 ? -1 : 1);
          a.x -= push;
          b.x += push;
        } else {
          const push = (overlapY / 2) * (dy < 0 ? -1 : 1);
          a.y -= push;
          b.y += push;
        }
      }
    }
    for (const n of physicsNodes) {
      if (n.y < anchor.y) n.y = anchor.y;
      n.x = Math.min(Math.max(n.x, 60), Math.max(width - 60, 60));
      n.y = Math.min(n.y, height - 30);
    }
  }
}

function tick() {
  const wrapper = document.getElementById("graph-wrapper");
  const wrapperRect = wrapper.getBoundingClientRect();
  const areaRect = document.getElementById("choices-area").getBoundingClientRect();
  const anchor = computeAnchor(wrapperRect);

  stepPhysics(anchor, wrapperRect.width, areaRect.height);
  resolveCollisions(anchor, wrapperRect.width, areaRect.height);

  const svg = document.getElementById("connector-svg");
  svg.innerHTML = "";
  svg.setAttribute("width", wrapperRect.width);
  svg.setAttribute("height", wrapperRect.height);

  physicsNodes.forEach((n) => {
    n.el.style.transform = "translate(" + (n.x - n.el.offsetWidth / 2) + "px, " + (n.y - n.el.offsetHeight / 2) + "px)";

    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", anchor.x);
    line.setAttribute("y1", anchor.y);
    line.setAttribute("x2", n.x);
    line.setAttribute("y2", n.y);
    line.setAttribute("stroke", "#333844");
    line.setAttribute("stroke-width", "2");
    svg.appendChild(line);
  });

  animationFrameId = requestAnimationFrame(tick);
}

function makeChoiceNode(option) {
  const node = document.createElement("div");
  node.className = "node choice";
  node.textContent = option.label;
  node.addEventListener("click", () => {
    state.push({ classId: option.classId, subclassId: option.subclassId });
    render();
  });
  return node;
}

function render() {
  const graph = document.getElementById("build-graph");
  graph.innerHTML = "";
  state.forEach((choice, index) => {
    if (index > 0) {
      const connector = document.createElement("div");
      connector.className = "connector";
      graph.appendChild(connector);
    }
    graph.appendChild(makeConfirmedNode(choice, index));
  });

  const options = computeNextOptions();
  const heading = document.getElementById("choices-heading");
  const area = document.getElementById("choices-area");
  area.innerHTML = "";
  heading.textContent = options.length === 0 ? "" : (
    state.length === 0 ? "Choisissez une classe de départ :" : "Prochain niveau — choisissez :"
  );

  // Nouvel ensemble d'options -> on repart d'une simulation fraîche,
  // dispersée autour de l'ancre (léger angle/rayon aléatoire pour éviter
  // que deux nœuds démarrent exactement superposés) : ça donne l'effet
  // "tentacules qui se déploient" à chaque nouveau choix.
  const wrapperRect = document.getElementById("graph-wrapper").getBoundingClientRect();
  const anchor = computeAnchor(wrapperRect);
  // Rayon "au repos" proportionnel au nombre de choix : sinon le ressort
  // tire tous les nœuds vers un anneau trop petit pour les contenir côte à
  // côte, et la répulsion (centre à centre) ne suffit pas à elle seule à
  // les en sortir — voir aussi `resolveCollisions` pour la garantie stricte
  // de non-chevauchement.
  restLength = Math.max(120, 60 + options.length * 26);
  physicsNodes = options.map((option) => {
    const el = makeChoiceNode(option);
    area.appendChild(el);
    const angle = Math.random() * Math.PI * 2;
    const radius = 10 + Math.random() * 20;
    return {
      x: anchor.x + Math.cos(angle) * radius,
      y: anchor.y + Math.abs(Math.sin(angle)) * radius,
      vx: 0,
      vy: 0,
      el,
    };
  });

  document.getElementById("undo-btn").disabled = state.length === 0;
  document.getElementById("build-status").classList.toggle("visible", state.length >= MAX_LEVEL);
  renderClassSummary();
}

document.getElementById("undo-btn").addEventListener("click", () => {
  state.pop();
  render();
});

document.getElementById("reset-btn").addEventListener("click", () => {
  state.length = 0;
  render();
});

document.getElementById("compact-toggle").addEventListener("change", (event) => {
  compactMode = event.target.checked;
  render();
});

render();
if (animationFrameId === null) {
  animationFrameId = requestAnimationFrame(tick);
}
</script>
</body>
</html>
"""
