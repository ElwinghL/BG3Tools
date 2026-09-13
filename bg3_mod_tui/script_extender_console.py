"""Interception de la console du Script Extender (BG3SE) — sous-tâche 11a
du TODO ("Console extender intercepter/flux").

**Portée stricte 11a** : lecture seule (on affiche ce que BG3SE journalise),
jamais d'écriture de commande vers le jeu (11b) ni d'auto-complétion (11c).

Mécanisme retenu, après investigation du dépôt et de la documentation
publique de BG3SE (https://github.com/Norbyte/bg3se) :

- BG3SE peut ouvrir une vraie fenêtre de console Win32 native (réglage
  `CreateConsole` de `ScriptExtenderSettings.json`, voir
  `game_deploy.SCRIPT_EXTENDER_DEFAULT_SETTINGS`, où il vaut `False` par
  défaut chez nous). Sous Proton, cette fenêtre est rendue via Wine — c'est
  précisément le lag que cette sous-tâche cherche à contourner. On ne pilote
  donc jamais cette console native : on ne la lance pas, on ne l'active pas.
- BG3SE journalise en revanche sa sortie dans des fichiers texte quand
  `EnableLogging` (et/ou `LogRuntime`/`LogCompile`/`LogFailedCompile`) est
  actif, sous le dossier `LogDirectory` — `My Documents\\OsirisLogs` par
  défaut, un dossier spécial Windows *distinct* de l'AppData où vit
  `Config.appdata_path` (`%LOCALAPPDATA%\\Larian Studios\\Baldur's Gate 3`).
  Sous Proton, "My Documents" et l'AppData Local partagent le même dossier
  utilisateur du préfixe (`drive_c/users/<user>/`) mais pas le même
  sous-dossier ; on retrouve donc d'abord ce dossier utilisateur (sans
  supposer le nom `steamuser` en dur) plutôt que de dériver le chemin
  directement depuis `appdata_path`.
- BG3SE ne documente pas de nom de fichier de log garanti stable (il peut
  varier selon le contexte de script — Lua serveur/client, Osiris — et le
  nom du fichier chargé) : on suit donc *tous* les `*.log` du dossier
  (`tail -F .../*.log`) plutôt que de parier sur un nom précis. `tail -F`
  (majuscule) suit aussi une rotation/un remplacement de fichier, utile si
  BG3SE recrée ses logs à chaque nouvelle session de jeu.

Conformément à la clarification d'Elwingh : la console BG3SE peut être un
outil externe qui vit dans son propre terminal, en dehors du TUI Textual
— ce module ne fait donc que *construire* la commande de suivi ; c'est
`terminal_launcher.open_in_terminal` (déjà utilisé par ce projet pour
relancer le TUI dans un terminal dédié) qui l'exécute dans un terminal
externe séparé, jamais un widget intégré au TUI."""

from __future__ import annotations

import shlex
from pathlib import Path

from bg3_mod_tui.platform_utils import find_proton_prefix, is_windows

OSIRIS_LOGS_DIRNAME = "OsirisLogs"


def find_proton_user_dir(reference_path: Path) -> Path | None:
    """Retrouve le dossier utilisateur Windows (`drive_c/users/<user>`) du
    préfixe Proton contenant `reference_path` (typiquement
    `Config.appdata_path`). Ne suppose pas le nom `steamuser` en dur :
    remonte les parents de `reference_path` jusqu'à trouver celui dont le
    parent est littéralement `drive_c/users` du préfixe trouvé — robuste à
    un nom d'utilisateur Proton différent."""
    prefix = find_proton_prefix(reference_path)
    if prefix is None:
        return None
    users_dir = prefix / "drive_c" / "users"
    resolved = reference_path.resolve()
    for parent in (resolved, *resolved.parents):
        if parent.parent == users_dir:
            return parent
    return None


def find_osiris_log_dir(appdata_path: Path) -> Path | None:
    """Retourne le dossier où BG3SE écrit ses logs par défaut (voir le
    module docstring), d'après `Config.appdata_path`. Ne vérifie pas que le
    dossier existe déjà — BG3SE ne le crée qu'à la première session de jeu
    avec le logging actif — c'est à l'appelant de gérer ce cas (voir
    `build_tail_command`, qui attend son apparition plutôt que d'échouer).

    Retourne `None` si le dossier utilisateur ne peut pas être déterminé
    (sous Linux/Proton : préfixe Proton introuvable à partir
    d'`appdata_path`, ex. configuration incomplète ou jeu non installé via
    Proton)."""
    if is_windows():
        return Path.home() / "Documents" / OSIRIS_LOGS_DIRNAME
    user_dir = find_proton_user_dir(appdata_path)
    if user_dir is None:
        return None
    return user_dir / "My Documents" / OSIRIS_LOGS_DIRNAME


def build_tail_command(log_dir: Path) -> list[str]:
    """Construit la commande à exécuter dans un terminal externe dédié
    (voir `terminal_launcher.open_in_terminal`) pour suivre en direct les
    logs BG3SE de `log_dir` : attend leur apparition (dossier pas encore
    créé si le jeu n'a pas encore tourné avec le logging actif, ou pas
    encore de fichier dedans), affiche un rappel du réglage nécessaire,
    puis les affiche en flux continu. Ne bloque jamais le TUI : cette
    commande est pensée pour tourner dans le terminal externe, pas dans le
    process du TUI."""
    if is_windows():
        quoted_dir = _ps_quote(str(log_dir))
        script = (
            f"$dir = {quoted_dir}; "
            "Write-Host 'Console Script Extender (BG3SE) : en attente des logs dans' $dir; "
            "Write-Host '(necessite EnableLogging=true dans ScriptExtenderSettings.json et le jeu lance)'; "
            "while (-not (Test-Path $dir) -or "
            "-not (Get-ChildItem -Path $dir -Filter *.log -ErrorAction SilentlyContinue)) "
            "{ Start-Sleep -Seconds 1 }; "
            "Get-Content -Path (Join-Path $dir '*.log') -Wait -Tail 200"
        )
        return ["powershell", "-NoProfile", "-NoExit", "-Command", script]

    quoted_dir = shlex.quote(str(log_dir))
    script = (
        f"dir={quoted_dir}; "
        'echo "Console Script Extender (BG3SE) : en attente des logs dans $dir"; '
        'echo "(necessite EnableLogging=true dans ScriptExtenderSettings.json et le jeu lance)"; '
        'while [ ! -d "$dir" ] || [ -z "$(ls -A "$dir" 2>/dev/null)" ]; do sleep 1; done; '
        'tail -n +1 -F "$dir"/*.log'
    )
    return ["bash", "-c", script]


def _ps_quote(value: str) -> str:
    """Échappe `value` pour l'insérer comme chaîne littérale PowerShell
    (guillemets simples, où seul `'` doit être doublé)."""
    return "'" + value.replace("'", "''") + "'"
