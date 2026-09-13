"""Écran principal : menu d'actions (téléchargement, nettoyage, extraction,
outils) plutôt qu'une liste de mods à parcourir."""

from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path
from typing import Callable, NamedTuple

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    SelectionList,
    TabbedContent,
    TabPane,
)
from textual.worker import Worker, WorkerState

from bg3_mod_tui.class_builder import DEFAULT_HTML_FILENAME, write_html
from bg3_mod_tui.compat_framework import (
    CompatibilityFrameworkError,
    build_pak as build_compat_framework_pak,
    find_divine_exe,
)
from bg3_mod_tui.config import ModToolsConfig, save_config
from bg3_mod_tui.crash_log import log_crash
from bg3_mod_tui.game_deploy import deploy_native_mod_loader, deploy_script_extender
from bg3_mod_tui.inventory import (
    NEXUS_MOD_URL,
    build_inventory,
    find_orphaned_archives,
    save_inventory,
    scan_all_archives,
)
from bg3_mod_tui.launcher import LauncherError, launch_tool, open_protontricks, resolve_wine_bin
from bg3_mod_tui.log_format import fmt_http_log_line
from bg3_mod_tui.linking import LinkingError, setup_links
from bg3_mod_tui.script_extender_console import build_tail_command, find_osiris_log_dir
from bg3_mod_tui.terminal_launcher import open_in_terminal
from bg3_mod_tui.mod_fixer_fork import ModFixerForkError, build_fork as build_mod_fixer_fork
from bg3_mod_tui.native_mods import (
    NativeModsManifestError,
    deploy_native_mods_from_manifest,
    load_manifest as load_native_mods_manifest,
)
from bg3_mod_tui.pak_metadata import archive_pak_identities, build_deployed_uuid_index
from bg3_mod_tui.pak_validator import validate_paks
from bg3_mod_tui.pak_origin import (
    find_orphaned_paks,
    load_manual_origins,
    match_orphan_by_name,
    match_orphan_by_uuid,
    save_manual_origin,
)
from bg3_mod_tui.platform_utils import find_proton_prefix, has_graphical_display, is_windows
from bg3_mod_tui.profile_archive import (
    ARCHIVE_SUFFIX,
    ProfileArchiveError,
    export_profile_archive,
    import_profile_archive,
)
from bg3_mod_tui.profiles import (
    ProfileError,
    ensure_default_profile,
    list_profiles,
    load_blacklisted_files,
    profile_data_dir,
    restore_profile,
    save_blacklisted_files,
    save_profile,
    slugify_profile_name,
)
from bg3_mod_tui.webserver import WebServerHandle, start_http_server
from bg3_mod_tui.wineprefix import WinePrefixError, optimize_prefix_for_tools
from bg3_mod_tui.mod_pipeline import (
    check_nexus_updates,
    clean_pak_files,
    cleanup_duplicate_archives,
    download_mods_from_links_file,
    download_subscribed_modio_mods,
    extract_archives_to_mods,
    redownload_nexus_mod,
)
from bg3_mod_tui.providers.modio import ModIOAPIError, ModIOClient
from bg3_mod_tui.providers.nexus import NexusAPIError, NexusClient
from bg3_mod_tui.tools_manager import ToolsError, download_and_extract_tool, find_executables, parse_tools_table
from bg3_mod_tui.usage_stats import increment_usage_stat, load_usage_stats, top_actions
from bg3_mod_tui.widgets.console_log import ConsoleLog
from bg3_mod_tui.widgets.download_console import DownloadProgressConsole


TOOL_ICON = "🛠"


def _human_size(size_bytes: int) -> str:
    """Formate une taille en octets en unité lisible (Ko/Mo/Go), pour le
    rapport d'archives orphelines (`run_orphaned_archives`)."""
    size = float(size_bytes)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{size:.1f} {unit}" if unit != "o" else f"{int(size)} {unit}"
        size /= 1024
    return f"{size:.1f} Go"


def _orphan_report_row(archive: dict, statut: str) -> str:
    """Formate une ligne de tableau Markdown pour le rapport d'archives
    orphelines (`run_orphaned_archives` / `_flush_orphans_progress`), avec
    une colonne Statut en plus du format historique — une ligne = une
    archive déjà traitée, suffisante à elle seule pour savoir ce qui a été
    décidé pour cette archive sans attendre la fin du lot."""
    origin = (
        f"[{archive['mod_name_guess']}]({archive['nexus_url']})"
        if archive.get("nexus_url")
        else (archive.get("mod_name_guess") or "?")
    )
    return (
        f"| {archive['file']} | {_human_size(archive['size_bytes'])} | "
        f"{origin} | {archive['modified'][:10]} | {statut} |"
    )

# Contraste renforcé pour les cases à cocher des `SelectionList` (utilisée
# par `NexusFileSelectionScreen` et `NexusBlacklistScreen`) : le style par
# défaut de Textual ne distingue coché/décoché que par la couleur d'un
# glyphe "X" toujours présent (rendu quasi invisible en le calquant sur le
# fond quand décoché) — sur ce thème sombre/bronze, l'écart entre les
# teintes par défaut ($panel-darken-2 vs $text-success) est trop subtil
# pour trancher au premier coup d'œil. On reprend le code couleur
# erreur/succès du thème (voir `theme.py`) — sans ambiguïté possible :
# décoché = rouge (`$error`), coché = sarcelle (`$success`) — jusque dans
# les caractères latéraux de la case (`▐▌`, dont la couleur suit celle du
# fond du bouton).
_SELECTION_LIST_CSS = """
SelectionList > .selection-list--button {
    color: $error;
    background: $panel;
    text-style: bold;
}
SelectionList > .selection-list--button-highlighted {
    color: $error-lighten-1;
    background: $panel;
    text-style: bold;
}
SelectionList > .selection-list--button-selected {
    color: $success;
    background: $panel;
    text-style: bold;
}
SelectionList > .selection-list--button-selected-highlighted {
    color: $success-lighten-1;
    background: $panel;
    text-style: bold;
}
"""


class _ToolListItem(ListItem):
    """Élément de liste représentant un exécutable : mémorise son chemin
    complet (utilisé pour le lancement) tout en n'affichant que son nom."""

    def __init__(self, exe_path: Path) -> None:
        self.exe_path = exe_path
        super().__init__(Label(f"{TOOL_ICON} {exe_path.name}"))


class ToolPickerScreen(ModalScreen[Path | None]):
    """Liste les exécutables trouvés sous Tools/, groupés par dossier
    d'outil, pour en choisir un à lancer (clic simple, ou sélection au
    clavier + bouton « Lancer »)."""

    CSS = """
    ToolPickerScreen {
        align: center middle;
    }
    #tool-picker-box {
        width: 80%;
        max-width: 100;
        height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #tool-groups {
        height: 1fr;
    }
    .tool-group-header {
        margin-top: 1;
        text-style: bold;
        /* `$text-accent` (pas `$accent` brut) : variante éclaircie générée
           par Textual spécifiquement pour du texte sur fond sombre — le
           bronze brut n'atteint pas le contraste AA (4.5:1) sur les
           panneaux les plus sombres. */
        color: $text-accent;
    }
    ListView {
        height: auto;
        background: transparent;
    }
    ListView > ListItem {
        margin-bottom: 1;
        padding: 0 1;
    }
    #tool-picker-buttons {
        height: auto;
        margin-top: 1;
    }
    #tool-picker-buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, executables: list[Path], project_root: Path) -> None:
        super().__init__()
        self._executables = executables
        self._project_root = project_root
        self._selected_exe: Path | None = executables[0] if executables else None

    def _group_label(self, exe: Path) -> str:
        try:
            relative = exe.relative_to(self._project_root)
        except ValueError:
            return str(exe.parent)
        parts = relative.parts
        # Le premier segment sous Tools/ identifie l'outil (ex: "Tools",
        # "BG3-Load-Order-Optimizer", ...) — on regroupe par ce dossier.
        return parts[1] if len(parts) > 1 else parts[0]

    @staticmethod
    def _group_sort_key(group_name: str) -> tuple[bool, str]:
        # ExportTools (LSLib) contient énormément d'exécutables annexes
        # (Divine, StoryCompiler, RconClient...) qui noieraient les outils
        # réellement utilisés au quotidien en tête de liste — on le relègue
        # toujours en dernier plutôt que de le laisser à sa place
        # alphabétique.
        return (group_name == "ExportTools", group_name)

    def compose(self) -> ComposeResult:
        with Vertical(id="tool-picker-box"):
            yield Label("Choisir un outil à lancer", classes="title")
            groups: dict[str, list[Path]] = {}
            for exe in self._executables:
                groups.setdefault(self._group_label(exe), []).append(exe)

            with VerticalScroll(id="tool-groups"):
                for group_name in sorted(groups, key=self._group_sort_key):
                    yield Label(group_name, classes="tool-group-header")
                    yield ListView(
                        *[_ToolListItem(exe) for exe in sorted(groups[group_name])]
                    )

            with Horizontal(id="tool-picker-buttons"):
                yield Button("Lancer", id="tool-picker-launch", variant="primary")
                yield Button("Annuler", id="tool-picker-cancel")

    @on(ListView.Highlighted)
    def handle_highlighted(self, event: ListView.Highlighted) -> None:
        if isinstance(event.item, _ToolListItem):
            self._selected_exe = event.item.exe_path

    @on(ListView.Selected)
    def handle_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, _ToolListItem):
            self.dismiss(event.item.exe_path)

    @on(Button.Pressed, "#tool-picker-launch")
    def handle_launch(self) -> None:
        self.dismiss(self._selected_exe)

    @on(Button.Pressed, "#tool-picker-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)


class NexusFileSelectionScreen(ModalScreen[list[int]]):
    """Demande, pour un mod Nexus proposant plusieurs fichiers (parfois de
    simples variantes alternatives dont une seule doit être installée),
    lesquels garder : flèches pour naviguer, espace pour cocher/décocher
    (tous cochés par défaut), Entrée ou bouton pour valider. Les fichiers
    décochés rejoignent la blacklist du profil actif — voir
    `mod_pipeline.download_mods_from_links_file` — et ne seront plus
    proposés tant qu'ils ne seront pas resélectionnés (ex: depuis
    l'inventaire)."""

    BINDINGS = [Binding("enter", "confirm", "Valider", priority=True)]

    CSS = _SELECTION_LIST_CSS + """
    NexusFileSelectionScreen {
        align: center middle;
    }
    #file-selection-box {
        width: 80%;
        max-width: 100;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #file-selection-list {
        height: auto;
        max-height: 20;
        margin-top: 1;
    }
    #file-selection-buttons {
        height: auto;
        margin-top: 1;
    }
    #file-selection-url {
        margin-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, mod_id: int, mod_name: str, candidates: list[tuple[int, str]]) -> None:
        super().__init__()
        self._mod_id = mod_id
        self._mod_name = mod_name
        self._candidates = candidates
        self._mod_url = f"{NEXUS_MOD_URL.format(id=mod_id)}?tab=files"

    def compose(self) -> ComposeResult:
        with Vertical(id="file-selection-box"):
            yield Label(f"Plusieurs fichiers pour « {self._mod_name} » (#{self._mod_id})", classes="title")
            yield Label(
                "Espace : cocher/décocher ceux à garder. Entrée : valider — "
                "les fichiers décochés ne seront plus proposés."
            )
            yield SelectionList[int](
                *[(file_name, file_id, True) for file_id, file_name in self._candidates],
                id="file-selection-list",
            )
            with Horizontal(id="file-selection-buttons"):
                if has_graphical_display():
                    yield Button("Ouvrir la page Nexus", id="file-selection-open-url")
                yield Button("Valider", id="file-selection-confirm", variant="primary")
            # Page Nexus (onglet Fichiers) pour comparer les candidats avant de
            # cocher/décocher — toujours affichée telle quelle (copiable à la
            # main), le bouton ci-dessus n'étant qu'un raccourci quand un
            # navigateur est disponible.
            yield Label(self._mod_url, id="file-selection-url")

    def on_mount(self) -> None:
        self.query_one("#file-selection-list", SelectionList).focus()

    def action_confirm(self) -> None:
        self.dismiss(self.query_one("#file-selection-list", SelectionList).selected)

    @on(Button.Pressed, "#file-selection-confirm")
    def handle_confirm(self) -> None:
        self.action_confirm()

    @on(Button.Pressed, "#file-selection-open-url")
    def handle_open_url(self) -> None:
        webbrowser.open(self._mod_url)
        # Cliquer sur le bouton lui donne le focus, ce qui couperait la
        # navigation aux flèches sur la liste tant qu'on ne re-clique pas
        # dessus — on lui rend systématiquement le focus derrière.
        self.query_one("#file-selection-list", SelectionList).focus()


class NestedArchiveSelectionScreen(ModalScreen[list[Path]]):
    """Demande, quand une archive de mod contient elle-même d'autres
    archives (.zip/.rar/.7z) imbriquées plutôt que des .pak directement
    (ex: plusieurs variantes empaquetées ensemble), lesquelles garder —
    même wizard que `NexusFileSelectionScreen` (flèches pour naviguer,
    espace pour cocher/décocher, tous cochés par défaut, Entrée ou bouton
    pour valider), sans les éléments propres à Nexus (mod_id, lien
    "Ouvrir sur Nexus") qui n'ont pas de sens pour un ZIP imbriqué
    quelconque. Les archives décochées sont ignorées ; les autres sont
    extraites à leur tour par `mod_pipeline.extract_archives_to_mods`."""

    BINDINGS = [Binding("enter", "confirm", "Valider", priority=True)]

    CSS = _SELECTION_LIST_CSS + """
    NestedArchiveSelectionScreen {
        align: center middle;
    }
    #nested-selection-box {
        width: 80%;
        max-width: 100;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #nested-selection-list {
        height: auto;
        max-height: 20;
        margin-top: 1;
    }
    #nested-selection-buttons {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, archive_name: str, candidates: list[Path]) -> None:
        super().__init__()
        self._archive_name = archive_name
        self._candidates = candidates

    def compose(self) -> ComposeResult:
        with Vertical(id="nested-selection-box"):
            yield Label(f"ZIP imbriqué(s) trouvé(s) dans « {self._archive_name} »", classes="title")
            yield Label(
                "Espace : cocher/décocher ceux à garder et extraire. Entrée : "
                "valider — les ZIP décochés seront ignorés."
            )
            yield SelectionList[Path](
                *[(path.name, path, True) for path in self._candidates],
                id="nested-selection-list",
            )
            with Horizontal(id="nested-selection-buttons"):
                yield Button("Valider", id="nested-selection-confirm", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#nested-selection-list", SelectionList).focus()

    def action_confirm(self) -> None:
        self.dismiss(self.query_one("#nested-selection-list", SelectionList).selected)

    @on(Button.Pressed, "#nested-selection-confirm")
    def handle_confirm(self) -> None:
        self.action_confirm()


class NexusBlacklistScreen(ModalScreen[list[tuple[int, int]] | None]):
    """Liste les fichiers Nexus écartés (blacklist) du profil actif — voir
    `NexusFileSelectionScreen` et `mod_pipeline.download_mods_from_links_file`
    — pour en resélectionner certains. Rien n'est coché par défaut : seuls
    les fichiers cochés ici sont retirés de la blacklist et seront donc
    reproposés (avec, si le mod a de nouveau plusieurs candidats, l'écran
    de choix qui réapparaît) au prochain téléchargement."""

    BINDINGS = [
        Binding("enter", "confirm", "Valider", priority=True),
        Binding("o", "open_url", "Ouvrir Nexus"),
    ]

    CSS = _SELECTION_LIST_CSS + """
    NexusBlacklistScreen {
        align: center middle;
    }
    #blacklist-box {
        width: 80%;
        max-width: 100;
        height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #blacklist-list {
        height: 1fr;
        margin-top: 1;
    }
    #blacklist-url {
        margin-top: 1;
        color: $text-muted;
    }
    #blacklist-buttons {
        height: auto;
        margin-top: 1;
    }
    #blacklist-buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, blacklist: dict[int, dict[int, str]]) -> None:
        super().__init__()
        self._blacklist = blacklist

    def compose(self) -> ComposeResult:
        with Vertical(id="blacklist-box"):
            yield Label("Fichiers Nexus écartés (profil actif)", classes="title")
            yield Label(
                "Espace : cocher ceux à réintégrer. Entrée : valider — ils seront "
                "reproposés au prochain téléchargement. 'o' ou le bouton : ouvrir "
                "la page Nexus du mod survolé, pour guider le choix."
            )
            options = [
                (f"#{mod_id} — {file_name}", (mod_id, file_id), False)
                for mod_id, files in sorted(self._blacklist.items())
                for file_id, file_name in sorted(files.items())
            ]
            yield SelectionList[tuple[int, int]](*options, id="blacklist-list")
            # Page Nexus du mod actuellement survolé — mise à jour au fil de la
            # navigation (voir `handle_highlighted`), toujours affichée telle
            # quelle (copiable à la main) ; le bouton n'est qu'un raccourci
            # quand un navigateur est disponible (voir `has_graphical_display`).
            yield Label("", id="blacklist-url")
            with Horizontal(id="blacklist-buttons"):
                if has_graphical_display():
                    yield Button("Ouvrir la page Nexus", id="blacklist-open-url")
                yield Button("Valider", id="blacklist-confirm", variant="primary")
                yield Button("Annuler", id="blacklist-cancel")

    def on_mount(self) -> None:
        selection_list = self.query_one("#blacklist-list", SelectionList)
        selection_list.focus()
        self._update_url_label()

    def _highlighted_mod_id(self) -> int | None:
        highlighted = self.query_one("#blacklist-list", SelectionList).highlighted_option
        if highlighted is None:
            return None
        mod_id, _file_id = highlighted.value
        return mod_id

    def _update_url_label(self) -> None:
        mod_id = self._highlighted_mod_id()
        url = f"{NEXUS_MOD_URL.format(id=mod_id)}?tab=files" if mod_id is not None else ""
        self.query_one("#blacklist-url", Label).update(url)

    @on(SelectionList.SelectionHighlighted, "#blacklist-list")
    def handle_highlighted(self) -> None:
        self._update_url_label()

    def action_confirm(self) -> None:
        self.dismiss(self.query_one("#blacklist-list", SelectionList).selected)

    def action_open_url(self) -> None:
        mod_id = self._highlighted_mod_id()
        if mod_id is not None:
            webbrowser.open(f"{NEXUS_MOD_URL.format(id=mod_id)}?tab=files")

    @on(Button.Pressed, "#blacklist-confirm")
    def handle_confirm(self) -> None:
        self.action_confirm()

    @on(Button.Pressed, "#blacklist-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#blacklist-open-url")
    def handle_open_url(self) -> None:
        self.action_open_url()
        # Cliquer sur le bouton lui donne le focus, ce qui couperait la
        # navigation aux flèches sur la liste tant qu'on ne re-clique pas
        # dessus — on lui rend systématiquement le focus derrière.
        self.query_one("#blacklist-list", SelectionList).focus()


class NexusOutdatedModsScreen(ModalScreen[list[int] | None]):
    """Sous-tâche 4d du TODO ("Câbler `check_nexus_updates` au
    téléchargement") : affiche les mods repérés comme obsolètes par
    `mod_pipeline.check_nexus_updates` (`report["outdated"]`, voir
    `ActionsScreen._write_nexus_updates_report`) juste après la
    vérification, pour proposer un re-téléchargement en un clic — sans
    quoi le rapport (`nexus_updates.md`) resterait un simple fichier à lire
    à part, sans lien avec le téléchargement.

    Même pattern que `NexusBlacklistScreen` : une `SelectionList` (rien
    coché par défaut) plutôt qu'un bouton par ligne — cocher les mods à
    mettre à jour puis valider en un clic reste "un clic" pour déclencher
    le re-téléchargement, tout en réutilisant un widget déjà en place dans
    cet écran plutôt que d'inventer un nouveau système de liste à boutons
    individuels."""

    BINDINGS = [
        Binding("enter", "confirm", "Valider", priority=True),
        Binding("o", "open_url", "Ouvrir Nexus"),
    ]

    CSS = _SELECTION_LIST_CSS + """
    NexusOutdatedModsScreen {
        align: center middle;
    }
    #outdated-box {
        width: 80%;
        max-width: 100;
        height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #outdated-list {
        height: 1fr;
        margin-top: 1;
    }
    #outdated-url {
        margin-top: 1;
        color: $text-muted;
    }
    #outdated-buttons {
        height: auto;
        margin-top: 1;
    }
    #outdated-buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, outdated: list[dict]) -> None:
        super().__init__()
        self._outdated = outdated

    def compose(self) -> ComposeResult:
        with Vertical(id="outdated-box"):
            yield Label("Mods Nexus obsolètes localement", classes="title")
            yield Label(
                "Espace : cocher les mods à mettre à jour. Entrée : "
                "re-télécharger les mods cochés (mêmes garanties que "
                "« Télécharger les mods » — wizard de variantes, "
                "blacklist). 'o' ou le bouton : ouvrir la page Nexus du "
                "mod survolé."
            )
            options = [
                (
                    f"{entry['mod_name_guess'] or entry['archive']} — "
                    f"local {entry['local_version'] or '?'} -> Nexus {entry['remote_version']}",
                    entry["nexus_mod_id"],
                    False,
                )
                for entry in sorted(
                    self._outdated, key=lambda e: e["mod_name_guess"] or e["archive"]
                )
            ]
            yield SelectionList[int](*options, id="outdated-list")
            yield Label("", id="outdated-url")
            with Horizontal(id="outdated-buttons"):
                if has_graphical_display():
                    yield Button("Ouvrir la page Nexus", id="outdated-open-url")
                yield Button("Re-télécharger la sélection", id="outdated-confirm", variant="primary")
                yield Button("Fermer", id="outdated-cancel")

    def on_mount(self) -> None:
        selection_list = self.query_one("#outdated-list", SelectionList)
        selection_list.focus()
        self._update_url_label()

    def _highlighted_mod_id(self) -> int | None:
        highlighted = self.query_one("#outdated-list", SelectionList).highlighted_option
        if highlighted is None:
            return None
        return highlighted.value

    def _update_url_label(self) -> None:
        mod_id = self._highlighted_mod_id()
        url = f"{NEXUS_MOD_URL.format(id=mod_id)}?tab=files" if mod_id is not None else ""
        self.query_one("#outdated-url", Label).update(url)

    @on(SelectionList.SelectionHighlighted, "#outdated-list")
    def handle_highlighted(self) -> None:
        self._update_url_label()

    def action_confirm(self) -> None:
        self.dismiss(self.query_one("#outdated-list", SelectionList).selected)

    def action_open_url(self) -> None:
        mod_id = self._highlighted_mod_id()
        if mod_id is not None:
            webbrowser.open(f"{NEXUS_MOD_URL.format(id=mod_id)}?tab=files")

    @on(Button.Pressed, "#outdated-confirm")
    def handle_confirm(self) -> None:
        self.action_confirm()

    @on(Button.Pressed, "#outdated-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#outdated-open-url")
    def handle_open_url(self) -> None:
        self.action_open_url()
        self.query_one("#outdated-list", SelectionList).focus()


class ProfileNamePromptScreen(ModalScreen[str | None]):
    """Demande un nom de profil (simple champ texte) avant sauvegarde."""

    CSS = """
    ProfileNamePromptScreen {
        align: center middle;
    }
    #profile-name-box {
        width: 60;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #profile-name-buttons {
        height: auto;
        margin-top: 1;
    }
    #profile-name-buttons Button {
        margin-right: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="profile-name-box"):
            yield Label("Nom du profil à sauvegarder", classes="title")
            yield Input(placeholder="ex: Run RP, Run Combat...", id="profile-name-input")
            with Horizontal(id="profile-name-buttons"):
                yield Button("Sauvegarder", id="profile-name-confirm", variant="primary")
                yield Button("Annuler", id="profile-name-cancel")

    def on_mount(self) -> None:
        self.query_one("#profile-name-input", Input).focus()

    @on(Input.Submitted, "#profile-name-input")
    def handle_submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    @on(Button.Pressed, "#profile-name-confirm")
    def handle_confirm(self) -> None:
        self.dismiss(self.query_one(
            "#profile-name-input", Input).value.strip() or None)

    @on(Button.Pressed, "#profile-name-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)


class PublicAddressPromptScreen(ModalScreen[tuple[str, str] | None]):
    """Demande l'adresse publique (URL) et le port, quand ils manquent au
    moment d'activer le serveur Web (bouton planète)."""

    CSS = """
    PublicAddressPromptScreen {
        align: center middle;
    }
    #public-address-box {
        width: 60;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #public-address-buttons {
        height: auto;
        margin-top: 1;
    }
    #public-address-buttons Button {
        margin-right: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="public-address-box"):
            yield Label("Adresse publique manquante", classes="title")
            yield Label("Nécessaire pour démarrer le serveur Web.")
            yield Label("Adresse publique (URL) :")
            yield Input(placeholder="ex: https://mon-ddns.exemple.net", id="public-address-url")
            yield Label("Port public :")
            yield Input(placeholder="ex: 8080", id="public-address-port")
            with Horizontal(id="public-address-buttons"):
                yield Button("Valider", id="public-address-confirm", variant="primary")
                yield Button("Annuler", id="public-address-cancel")

    def on_mount(self) -> None:
        self.query_one("#public-address-url", Input).focus()

    @on(Button.Pressed, "#public-address-confirm")
    def handle_confirm(self) -> None:
        url = self.query_one("#public-address-url", Input).value.strip()
        port = self.query_one("#public-address-port", Input).value.strip()
        if not url or not port:
            return
        self.dismiss((url, port))

    @on(Button.Pressed, "#public-address-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)


class ImportArchivePromptScreen(ModalScreen[str | None]):
    """Demande le chemin d'une archive de profil (.tar.zst) à importer."""

    CSS = """
    ImportArchivePromptScreen {
        align: center middle;
    }
    #import-archive-box {
        width: 80;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #import-archive-buttons {
        height: auto;
        margin-top: 1;
    }
    #import-archive-buttons Button {
        margin-right: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="import-archive-box"):
            yield Label("Chemin de l'archive de profil à importer", classes="title")
            yield Input(placeholder="ex: /home/.../MonProfil.bg3profile.tar.zst", id="import-archive-input")
            with Horizontal(id="import-archive-buttons"):
                yield Button("Importer", id="import-archive-confirm", variant="primary")
                yield Button("Annuler", id="import-archive-cancel")

    def on_mount(self) -> None:
        self.query_one("#import-archive-input", Input).focus()

    @on(Input.Submitted, "#import-archive-input")
    def handle_submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    @on(Button.Pressed, "#import-archive-confirm")
    def handle_confirm(self) -> None:
        self.dismiss(self.query_one(
            "#import-archive-input", Input).value.strip() or None)

    @on(Button.Pressed, "#import-archive-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)


class ManualPakOriginPromptScreen(ModalScreen[str | None]):
    """Étape 3 (dernier recours) de `pak_origin` : demande à l'utilisateur
    un lien Nexus/mod.io pour un .pak isolé qu'aucun matching automatique
    (nom, puis UUID) n'a permis de relier à une archive connue — voir
    `ActionsScreen._prompt_manual_pak_origins`."""

    CSS = """
    ManualPakOriginPromptScreen {
        align: center middle;
    }
    #manual-origin-box {
        width: 80;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #manual-origin-buttons {
        height: auto;
        margin-top: 1;
    }
    #manual-origin-buttons Button {
        margin-right: 1;
    }
    """

    def __init__(self, pak_file: str) -> None:
        super().__init__()
        self._pak_file = pak_file

    def compose(self) -> ComposeResult:
        with Vertical(id="manual-origin-box"):
            yield Label(f".pak isolé sans origine connue : {self._pak_file}", classes="title")
            yield Label(
                "Aucune archive locale ni UUID connu ne correspond — colle le lien "
                "Nexus ou mod.io de ce mod (laisse vide pour ignorer) :"
            )
            yield Input(
                placeholder="ex: https://www.nexusmods.com/baldursgate3/mods/12345",
                id="manual-origin-input",
            )
            with Horizontal(id="manual-origin-buttons"):
                yield Button("Enregistrer", id="manual-origin-confirm", variant="primary")
                yield Button("Ignorer", id="manual-origin-cancel")

    def on_mount(self) -> None:
        self.query_one("#manual-origin-input", Input).focus()

    @on(Input.Submitted, "#manual-origin-input")
    def handle_submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    @on(Button.Pressed, "#manual-origin-confirm")
    def handle_confirm(self) -> None:
        self.dismiss(self.query_one(
            "#manual-origin-input", Input).value.strip() or None)

    @on(Button.Pressed, "#manual-origin-cancel")
    def handle_cancel(self) -> None:
        self.dismiss(None)


NEW_PROFILE_OPTION = "__new_profile__"


class _ActiveTask(NamedTuple):
    """Une tâche "Tâches" actuellement en cours d'exécution, indexée par
    son `Worker` Textual (voir `ActionsScreen._start_task` et
    `ActionsScreen.on_worker_state_changed`, sous-tâche 7b du TODO
    "Vue par onglets").

    - `resource_tags` : les ressources (fichiers/dossiers) que la tâche
      écrit — voir `_resource_conflict` ; un ensemble vide signifie que la
      tâche ne fait que lire/écrire des fichiers qui lui sont propres
      (rapport isolé, etc.) et peut tourner aux côtés de n'importe quelle
      autre tâche.
    - `tab_id` : l'onglet (`#tasks-tabs` ou `#tools-tabs` selon `pool`,
      voir `_tabbed_content_for_tab`) où cette tâche écrit ses logs
      (l'onglet principal de son `pool` si aucune autre tâche du même pool
      n'était active à son lancement, sinon un onglet dynamique dédié —
      voir `_acquire_task_console`).
    - `write` : le callback d'écriture de cette tâche, SANS
      `call_from_thread` (voir `_acquire_task_console`) — réutilisé par
      `on_worker_state_changed`, qui tourne déjà sur le thread UI, pour
      afficher une erreur de worker dans la BONNE console/onglet plutôt
      que dans l'onglet "Tâches" principal par défaut.
    - `pool` : "tasks" (console "Tâches", mods/profils...) ou "tools"
      (console "Outils" — voir `_MAIN_CONSOLES` et sous-tâche 7d). Sert
      UNIQUEMENT à choisir la console/l'onglet dynamique dans
      `_acquire_task_console` : le verrouillage par ressource
      (`_resource_conflict`, dans `_start_task`) reste calculé sur
      `self._active_tasks` en entier, tous pools confondus — deux tâches
      qui écrivent dans les mêmes fichiers (ex: "Extraire vers Mods/" et
      "Compiler Compat. Framework", toutes deux taguées "mods-dir") doivent
      rester mutuellement exclusives même si elles logguent dans des
      consoles différentes.
    """

    resource_tags: frozenset[str]
    tab_id: str
    write: Callable[[str], None]
    pool: str = "tasks"


def _resource_conflict(
    active_resource_tags: list[frozenset[str]], requested: frozenset[str]
) -> frozenset[str]:
    """Étiquettes de `requested` déjà détenues par une tâche active
    (`active_resource_tags`, une liste des `resource_tags` de chaque
    tâche actuellement en cours) — fonction pure, testable sans app
    Textual (voir `tests/test_actions_task_tabs.py`). Un ensemble vide en
    retour signifie qu'aucune ressource commune n'empêche de lancer la
    nouvelle tâche."""
    held: frozenset[str] = frozenset()
    for tags in active_resource_tags:
        held |= tags
    return requested & held


def _run_task_sequence(
    steps: list[tuple[str, Callable[[Callable[[str], None]], bool]]],
    log: Callable[[str], None],
) -> bool:
    """Enchaîne `steps` (couples libellé + fonction "tâche" acceptant `log`
    et retournant `True`/`False` selon son succès) dans l'ordre, en
    journalisant une progression "[i/total]" avant chacune et en
    s'arrêtant à la première étape en échec (voir `ActionsScreen.
    run_update_all`, seul appelant actuel — le bouton "Tout mettre à jour").

    Factorisée en fonction MODULE-LEVEL pure (aucune dépendance à `self`),
    sur le même principe que `_resource_conflict` ci-dessus, pour rester
    testable sans app Textual (voir `tests/test_actions_task_tabs.py`) :
    seul CET enchaînement/arrêt-au-premier-échec est testé ainsi, les
    fonctions `task` elles-mêmes (ex: `_download_tools_task`) restant
    couplées à `self._config` et non testées ici.

    Retourne `True` si toutes les étapes ont réussi, `False` dès qu'une a
    échoué."""
    total = len(steps)
    for index, (label, task) in enumerate(steps, start=1):
        log(f"[bold]===== [{index}/{total}] {label} =====[/bold]")
        if not task(log):
            log(
                f"[#C46F6F]« {label} » a échoué : arrêt de la séquence "
                f"« Tout mettre à jour » ({index}/{total} étape(s) "
                f"tentée(s), les suivantes dépendent de celle-ci).[/#C46F6F]"
            )
            return False
    log(f"===== Terminé : {total}/{total} étapes réussies. =====")
    return True


class ActionsScreen(Screen):
    """Menu d'actions pour préparer/installer les mods BG3."""

    CSS = """
    #actions-menu {
        width: 40;
        border: round $accent;
        padding: 1 2;
    }
    #menu-buttons {
        height: 80%;
    }
    #menu-buttons Button {
        width: 100%;
        margin-bottom: 1;
    }
    /* Disposition demandée par Elwingh (sous-tâche 7) : les trois consoles
       (principale/Tâches, Outils, Web) doivent rester VISIBLES simultanément
       — plus question de les cacher derrière un seul TabbedContent à 4
       onglets qu'il fallait cliquer pour changer (régression de 7a/7c, qui
       n'avait gardé que des onglets). Principale en haut à gauche (avec ses
       propres onglets dynamiques pour les tâches en parallèle, sous-tâche
       7b), Web en haut à droite (pas d'onglets, sous-tâche 7d), Outils sur
       toute la largeur en bas (avec ses propres onglets dynamiques,
       sous-tâche 7d) — bordures laissées aux couleurs $panel/$accent
       d'origine (pas de code couleur rouge/vert/bleu par console, qui
       n'était qu'un repère visuel temporaire pour valider la disposition). */
    #logs-column {
        margin-left: 2;
        width: 1fr;
        height: 1fr;
    }
    #logs-top {
        height: 3fr;
    }
    #tasks-tabs {
        width: 3fr;
    }
    #tasks-tabs TabPane {
        padding: 0;
    }
    #tools-tabs {
        height: 1fr;
    }
    #tools-tabs TabPane {
        padding: 0;
    }
    #actions-log {
        border: round $panel;
        height: 1fr;
    }
    #tools-log {
        border: round $accent;
        height: 1fr;
    }
    #actions-body {
        height: 1fr;
    }
    #action-quit {
        dock: bottom;
        width: 100%;
    }
    #profile-bar {
        height: auto;
        padding: 0 2;
        margin-bottom: 1;
        align: right middle;
    }
    #profile-bar Label {
        margin-right: 1;
        padding-top: 1;
    }
    #profile-select {
        width: 40;
    }
    /* Barre des "quick actions" (3 boutons d'action les plus utilisés du
       profil actif, voir `_refresh_quick_actions`) — masquée tant qu'aucun
       bouton d'action n'a encore été utilisé (voir `top_actions`). */
    #quick-actions-bar {
        height: auto;
        padding: 0 2;
        margin-bottom: 1;
        align: left middle;
    }
    #quick-actions-bar Label {
        margin-right: 1;
    }
    #quick-actions-bar Button {
        margin-right: 1;
        width: auto;
    }
    /* Bouton "internet" : un bouton normal comme les autres (couleur selon
       l'état via la variante warning/error/success standard de Button) —
       icône et image abandonnées (peu lisibles/non fiables selon le
       terminal), on garde juste le code couleur. */
    #planet-button {
        margin-left: 2;
        width: 14;
    }
    #web-console-log {
        width: 1fr;
        border: round $accent;
        height: 1fr;
    }
    #downloads-progress {
        border: round $accent;
        height: 1fr;
    }
    """

    BINDINGS = [("q", "quit_app", "Quitter")]

    # Bouton d'action à ne PAS suivre par `usage_stats` malgré son id
    # préfixé "action-" : "Quitter" n'est pas une action métier du menu
    # (téléchargement, nettoyage, outil...) et n'a pas vocation à devenir
    # une quick action.
    _UNTRACKED_ACTION_ID = "action-quit"

    def __init__(self, config: ModToolsConfig) -> None:
        super().__init__()
        self._config = config
        self._web_server_handle = None
        # Onglets de logs dynamiques + verrouillage par ressource pour les
        # tâches "Tâches" (voir `_start_task`, `_acquire_task_console`,
        # sous-tâche 7b du TODO "Vue par onglets"). Copie d'instance de
        # `_LOG_TAB_LABELS` (plutôt que de muter l'attribut de classe) :
        # chaque onglet dynamique y ajoute son propre libellé de base.
        self._log_tab_labels: dict[str, str] = dict(self._LOG_TAB_LABELS)
        self._active_tasks: dict[Worker, _ActiveTask] = {}
        self._dynamic_task_tab_seq = 0

    def _profile_select_options(self) -> list[tuple[str, str]]:
        ensure_default_profile(self._config.profiles_dir)
        options = [(name, name)
                   for name in list_profiles(self._config.profiles_dir)]
        options.append(("+ Nouveau profil...", NEW_PROFILE_OPTION))
        return options

    def compose(self) -> ComposeResult:
        with Horizontal(id="profile-bar"):
            yield Label("Profil :")
            ensure_default_profile(self._config.profiles_dir)
            profiles = list_profiles(self._config.profiles_dir)
            active = self._config.active_profile if self._config.active_profile in profiles else Select.NULL
            yield Select(
                self._profile_select_options(),
                value=active,
                prompt="(aucun profil sauvegardé)",
                id="profile-select",
            )
            yield Button(
                "Web",
                id="planet-button",
                variant="warning" if not self._config.has_public_address() else "error",
            )
        # Rempli/rafraîchi dynamiquement par `_refresh_quick_actions` (rien
        # à monter tout de suite : les boutons "action-*" originaux, dont on
        # a besoin pour connaître libellé/tooltip, ne sont eux-mêmes montés
        # qu'après compose()).
        with Horizontal(id="quick-actions-bar"):
            yield Label("Actions rapides :")
        with Horizontal(id="actions-body"):
            with Vertical(id="actions-menu"):
                yield Label("BG3 Mod Tools", classes="title")
                with VerticalScroll(id="menu-buttons"):
                    yield Button(
                        "Télécharger les mods",
                        id="action-download-mods",
                        tooltip=(
                            "Télécharge la dernière version de chaque mod listé dans "
                            "nexus_links_to_add.md (un lien ou ID Nexus par ligne, MAIN/"
                            "UPDATE/OPTIONAL confondus), PUIS récupère les mods auxquels "
                            "ton compte mod.io est abonné. Les deux vers "
                            "Archives_installees/ (nécessite NEXUS_API_KEY et/ou "
                            "MODIO_API_KEY dans .env)."
                        ),
                    )
                    yield Button(
                        "Nettoyer les .pak",
                        id="action-clean-paks",
                        tooltip="Supprime tous les fichiers .pak actuellement présents dans Mods/ du jeu.",
                    )
                    yield Button(
                        "Sync. modsettings.lsx",
                        id="action-sync-modsettings",
                        tooltip=(
                            "Recale modsettings.lsx (l'ordre de charge du profil actif) "
                            "sur les mods réellement présents dans Mods/ — ajoute les "
                            "entrées manquantes, retire celles dont le .pak n'existe plus."
                        ),
                    )
                    yield Button(
                        "Extraire vers Mods/",
                        id="action-extract",
                        tooltip=(
                            "Traite les archives téléchargées : les .pak trouvés sont "
                            "copiés dans Mods/ ; les mods \"loose files\" (dossier "
                            "Generated/, Public/, ... sans .pak) sont fusionnés dans "
                            "DataMods/ puis reliés par hardlink dans Data/ du jeu ; le "
                            "reste est mis de côté pour examen manuel."
                        ),
                    )
                    yield Button(
                        "Tout mettre à jour (outils + Compat Framework + Mod Fixer)",
                        id="action-update-all",
                        tooltip=(
                            "Enchaîne dans l'ordre : MAJ des outils listés dans "
                            "Tools/TOOLS.md (BG3 Mod Manager, Load Order Optimizer, "
                            "Script Extender, ExportTools/LSLib, Para Tool...), puis "
                            "compilation de BG3 Compatibility Framework en .pak via "
                            "Divine.exe (LSLib), puis fork de Mod Fixer (Nexus #141) "
                            "avec un meta.lsx propre — avec une progression [i/3] dans "
                            "le log. S'arrête à la première étape en échec (les "
                            "suivantes dépendent de Divine.exe téléchargé par la 1ère)."
                        ),
                    )
                    yield Button(
                        "Lancer un outil...",
                        id="action-launch-tool",
                        tooltip=(
                            "Choisit un exécutable trouvé sous Tools/ et le lance en "
                            "arrière-plan (sous Linux, via le préfixe Proton de BG3 "
                            "uniquement, pour un environnement cohérent avec le jeu)."
                        ),
                    )
                    yield Button(
                        "Build de classes...",
                        id="action-class-builder",
                        disabled=True,
                        tooltip=(
                            "Génère une page HTML pour planifier un build multiclasse "
                            "niveau par niveau, servie par le serveur Web (bouton "
                            "planète) et ouverte dans le navigateur par défaut — "
                            "nécessite donc de l'avoir démarré au préalable (grisé "
                            "sinon). Données de classes/sous-classes limitées au "
                            "vanilla BG3 (niveau 1 à 12)."
                        ),
                    )
                    yield Button(
                        "Console Script Extender...",
                        id="action-se-console",
                        tooltip=(
                            "Ouvre un terminal externe dédié qui suit en direct les logs "
                            "de BG3 Script Extender (évite la console native, laggy sous "
                            "Proton) — lecture seule, rien n'est écrit vers le jeu. "
                            "Nécessite EnableLogging=true dans ScriptExtenderSettings.json "
                            "(voir déploiement du Script Extender) et attend que le jeu "
                            "tourne s'il n'est pas encore lancé."
                        ),
                    )
                    if not is_windows():
                        yield Button(
                            "Ouvrir protontricks",
                            id="action-protontricks",
                            tooltip=(
                                "Ouvre l'interface winetricks (via protontricks) sur le "
                                "préfixe Proton de BG3, pour ses réglages Wine (DLL "
                                "overrides, rendu logiciel WPF, etc.)."
                            ),
                        )
                    yield Button(
                        "Inventaire des mods",
                        id="action-inventory",
                        tooltip=(
                            "Génère un inventaire JSON (mods_inventory.json) listant les "
                            ".pak de Mods/ et toutes les archives connues, avec leur "
                            "origine Nexus (ID/version/URL) reconstruite quand possible."
                        ),
                    )
                    yield Button(
                        "Archives orphelines...",
                        id="action-orphaned-archives",
                        tooltip=(
                            "Liste les archives de _installees qu'aucun .pak/DLL "
                            "actuellement déployé ne référence (mod probablement "
                            "désinstallé depuis) — rapport dans "
                            "archives_orphelines.md sous le profil actif "
                            "(BG3_Managed/Profiles/...), rien n'est supprimé "
                            "automatiquement."
                        ),
                    )
                    yield Button(
                        "Origine des .pak isolés...",
                        id="action-orphan-paks",
                        tooltip=(
                            "Pour chaque .pak de Mods/ sans archive connue (glisser-déposé "
                            "direct, hors circuit Nexus/mod.io de ce TUI) : tente une "
                            "correspondance par nom puis par UUID réel (meta.lsx), et "
                            "demande en dernier recours un lien Nexus/mod.io à mémoriser "
                            "pour ne plus le redemander."
                        ),
                    )
                    yield Button(
                        "Valider les .pak déployés...",
                        id="action-validate-paks",
                        tooltip=(
                            "Check structurel natif (sans Divine.exe) de chaque .pak "
                            "actuellement présent dans Mods/ : ouvre le header LSPK et "
                            "décompresse un échantillon de ses entrées pour détecter une "
                            "corruption — rapport dans pak_validation.md sous le profil "
                            "actif. Lecture seule : ne génère pas modsettings.lsx et ne "
                            "lance pas le jeu. Pas un remplacement fiable à 100% de "
                            "Divine.exe, juste un check rapide (voir pak_validator.py)."
                        ),
                    )
                    yield Button(
                        "Vérifier les mises à jour Nexus...",
                        id="action-nexus-updates",
                        tooltip=(
                            "Compare la version de chaque archive Nexus connue "
                            "localement à la version actuellement publiée sur "
                            "Nexus, pour repérer les mods obsolètes — rapport "
                            "dans nexus_updates.md sous le profil actif "
                            "(nécessite NEXUS_API_KEY, rien n'est téléchargé "
                            "automatiquement)."
                        ),
                    )
                    yield Button(
                        "Fichiers Nexus écartés...",
                        id="action-nexus-blacklist",
                        tooltip=(
                            "Revoit les fichiers Nexus écartés lors d'un choix précédent "
                            "entre plusieurs variantes d'un même mod (profil actif) — "
                            "coche ceux à réintégrer pour qu'ils soient reproposés au "
                            "prochain téléchargement."
                        ),
                    )
                    yield Button(
                        "Déployer mods DLL",
                        id="action-native-mods",
                        tooltip=(
                            "Relie par hardlink les mods DLL listés dans "
                            "native_mods_manifest.json vers bin/NativeMods/ du jeu (via "
                            "Native Mod Loader)."
                        ),
                    )
                    if not is_windows():
                        yield Button(
                            "Optimiser le préfixe",
                            id="action-optimize-prefix",
                            tooltip=(
                                "Applique aux outils tiers (pas au jeu) les réglages Wine "
                                "recommandés (DLL overrides, etc.) dans le préfixe Proton "
                                "de BG3, pour limiter les glitchs visuels."
                            ),
                        )
                    yield Button(
                        "Exporter le profil actif",
                        id="action-export-profile",
                        tooltip=(
                            "Exporte le profil actif (modsettings.lsx + liste des mods "
                            "avec leur origine) dans une archive .tar.zst partageable "
                            "avec quelqu'un d'autre."
                        ),
                    )
                    yield Button(
                        "Importer un profil...",
                        id="action-import-profile",
                        tooltip="Importe une archive de profil (.tar.zst) exportée par un autre BG3 Mod TUI.",
                    )
                yield Button("Quitter", id="action-quit", variant="error")
            with Vertical(id="logs-column"):
                with Horizontal(id="logs-top"):
                    with TabbedContent(id="tasks-tabs"):
                        with TabPane("Tâches", id="actions-log-tab"):
                            yield ConsoleLog(id="actions-log", wrap=True, highlight=True, markup=True)
                        with TabPane("Téléchargements", id="downloads-log-tab"):
                            yield DownloadProgressConsole(id="downloads-progress")
                    yield ConsoleLog(id="web-console-log", wrap=True, highlight=True, markup=True)
                with TabbedContent(id="tools-tabs"):
                    with TabPane("Outils", id="tools-log-tab"):
                        yield ConsoleLog(id="tools-log", wrap=True, highlight=True, markup=True)
        yield Footer()

    # Libellés de base des onglets de consoles (utilisés pour reconstruire le
    # texte avec l'indicateur "●" quand un onglet inactif reçoit un message).
    # Web n'y figure plus : elle est toujours visible (sous-tâche 7c/7d),
    # plus besoin d'indicateur d'activité pour un onglet caché.
    _LOG_TAB_LABELS = {
        "actions-log-tab": "Tâches",
        "downloads-log-tab": "Téléchargements",
        "tools-log-tab": "Outils",
    }

    def _tabbed_content_for_tab(self, tab_id: str) -> TabbedContent | None:
        """Les onglets dynamiques (sous-tâche 7d) vivent dans deux
        `TabbedContent` distincts depuis que Web en est sortie (toujours
        visible, plus dans un onglet) : `#tasks-tabs` (pool "tasks") et
        `#tools-tabs` (pool "tools"). `tab_id` est unique entre les deux,
        donc on essaie l'un puis l'autre plutôt que de maintenir une carte
        séparée tab_id -> conteneur."""
        for selector in ("#tasks-tabs", "#tools-tabs"):
            try:
                tabbed_content = self.query_one(selector, TabbedContent)
                tabbed_content.get_tab(tab_id)
            except Exception:
                continue
            return tabbed_content
        return None

    def _mark_log_tab_active(self, tab_id: str) -> None:
        """Ajoute un indicateur "●" au libellé de l'onglet `tab_id` si ce
        n'est pas l'onglet actuellement affiché, pour signaler discrètement
        qu'une console en arrière-plan a reçu un nouveau message. Fonctionne
        aussi bien pour les onglets statiques que pour un onglet dynamique
        de tâche (voir `_acquire_task_console`), tant que son libellé de
        base est enregistré dans `self._log_tab_labels`."""
        tabbed_content = self._tabbed_content_for_tab(tab_id)
        if tabbed_content is None or tabbed_content.active == tab_id:
            return
        tab = tabbed_content.get_tab(tab_id)
        base_label = self._log_tab_labels.get(tab_id, str(tab.label))
        tab.label = f"{base_label} ●"

    def _clear_log_tab_indicator(self, tab_id: str) -> None:
        tabbed_content = self._tabbed_content_for_tab(tab_id)
        if tabbed_content is None:
            return
        tab = tabbed_content.get_tab(tab_id)
        tab.label = self._log_tab_labels.get(tab_id, str(tab.label))

    @on(TabbedContent.TabActivated, "#tasks-tabs")
    @on(TabbedContent.TabActivated, "#tools-tabs")
    def handle_log_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._clear_log_tab_indicator(event.pane.id or "")

    # Console principale de chaque pool (`_ActiveTask.pool`) : (tab_id,
    # méthode d'écriture directe, sans call_from_thread). "tasks" = onglet
    # "Tâches" (mods, profils...) ; "tools" = onglet "Outils" (téléchargement
    # d'outils, compilation Compat. Framework/Mod Fixer, lancement d'un
    # exécutable, protontricks, optimisation du préfixe — sous-tâche 7d).
    def _main_console_for_pool(self, pool: str) -> tuple[str, Callable[[str], None]]:
        if pool == "tools":
            return "tools-log-tab", self._tool_log
        return "actions-log-tab", self._log

    def _acquire_task_console(
        self, title: str, pool: str = "tasks"
    ) -> tuple[Callable[[str], None], Callable[[str], None], str]:
        """Choisit la console où une tâche doit écrire ses logs (appelée
        UNIQUEMENT depuis le thread UI, avant de lancer le worker — voir
        `_start_task`) :

        - Si aucune tâche du MÊME `pool` n'est actuellement active (parmi
          `self._active_tasks`), la tâche utilise la console principale de
          ce pool (`_main_console_for_pool` : "Tâches" ou "Outils"), comme
          avant ce mécanisme.
        - Sinon (une tâche de ce pool tourne déjà), un nouvel onglet est créé
          dynamiquement (`TabbedContent.add_pane`) avec sa propre
          `ConsoleLog`, pour ne pas mélanger deux flux de logs différents
          dans une seule console. Son libellé reprend le nom de l'action
          (`title`) suivi d'un numéro de séquence, ex. "Extraire vers
          Mods/ (2)".

        Ces onglets dynamiques ne sont PAS fermés/supprimés
        automatiquement à la fin de la tâche : Textual permet de le faire
        (`TabbedContent.remove_pane`), mais rien ne presse l'utilisateur de
        les voir disparaître — il peut encore vouloir relire le log après
        coup. Les garder indéfiniment (jusqu'à la fermeture de l'appli) est
        le choix le plus simple ; un bouton de fermeture par onglet est un
        raffinement d'UI non demandé par le TODO, laissé pour plus tard si
        le besoin s'en fait sentir.

        Retourne `(log, write, tab_id)` : `log` est sûre à appeler depuis
        n'importe quel thread (elle fait elle-même le `call_from_thread`,
        comme `_log`/`_tool_log`) et c'est elle qui est passée aux workers
        `thread=True`. `write` est la version SANS `call_from_thread` —
        `call_from_thread` refuse justement d'être appelée depuis le thread
        UI (`RuntimeError`) — à utiliser à la place de `log` par tout code
        qui tourne déjà sur le thread UI, comme `on_worker_state_changed`
        pour signaler une erreur de worker dans la bonne console.
        """
        main_tab_id, main_write = self._main_console_for_pool(pool)
        active_in_pool = [task for task in self._active_tasks.values() if task.pool == pool]
        if not active_in_pool:
            def write_main(message: str) -> None:
                try:
                    main_write(message)
                except Exception:
                    return

            def log_main(message: str) -> None:
                self.app.call_from_thread(write_main, message)

            return log_main, write_main, main_tab_id

        self._dynamic_task_tab_seq += 1
        seq = self._dynamic_task_tab_seq
        tab_id = f"dyn-task-log-tab-{seq}"
        console_id = f"dyn-task-log-{seq}"
        label = f"{title} ({seq})"
        self._log_tab_labels[tab_id] = label

        tabs_selector = "#tasks-tabs" if pool == "tasks" else "#tools-tabs"
        tabbed_content = self.query_one(tabs_selector, TabbedContent)
        tabbed_content.add_pane(
            TabPane(
                label,
                ConsoleLog(id=console_id, wrap=True, highlight=True, markup=True),
                id=tab_id,
            )
        )

        def write(message: str) -> None:
            try:
                self.query_one(f"#{console_id}", ConsoleLog).write(message)
            except Exception:
                return
            self._mark_log_tab_active(tab_id)

        def log(message: str) -> None:
            self.app.call_from_thread(write, message)

        return log, write, tab_id

    def _start_task(
        self,
        *,
        title: str,
        resource_tags: frozenset[str],
        launch: Callable[[Callable[[str], None]], "Worker | None"],
        pool: str = "tasks",
    ) -> None:
        """Point d'entrée commun à tous les boutons/évènements qui lancent
        un worker `@work` écrivant dans une console à onglets dynamiques
        (voir les `handle_*` correspondants). `pool` sélectionne la console
        principale/le groupe de verrouillage-onglet : "tasks" (console
        "Tâches", par défaut) ou "tools" (console "Outils" — sous-tâche 7d).
        Deux responsabilités :

        1. Détection "une tâche de ce pool tourne déjà" + routage vers la
           bonne console (`_acquire_task_console`) : le mécanisme retenu est un
           simple dictionnaire `self._active_tasks` (worker -> ressources
           tenues + onglet), peuplé ici et vidé par
           `on_worker_state_changed` dès que le `Worker` Textual associé
           atteint un état terminal (succès, erreur ou annulation). C'est
           plus robuste qu'un compteur manuel incrémenté/décrémenté à la
           main dans chacune des ~15 méthodes `run_*` (un `return`
           anticipé ou une exception non prévue oublierait de le
           décrémenter) : on s'appuie sur le cycle de vie déjà fiable des
           workers Textual, qui poste toujours un `Worker.StateChanged`
           terminal quel que soit le chemin de sortie du thread.
        2. Verrouillage par ressource pour la sous-tâche 3 du TODO : si
           `resource_tags` n'est pas vide et qu'une tâche déjà active
           déclare au moins une étiquette en commun (voir
           `_resource_conflict`), la nouvelle tâche n'est PAS lancée — un
           message l'explique dans la console principale. Ça évite deux
           écritures concurrentes dans les mêmes fichiers (Mods/,
           modsettings.lsx, mods DLL...), ce que la création d'un onglet
           séparé ne résout pas à elle seule (le TODO le souligne
           explicitement). Les actions à lecture seule (rapport isolé,
           scan sans écriture dans Mods/) déclarent `resource_tags=
           frozenset()` et tournent donc toujours librement en parallèle.
           Ce verrouillage porte sur `self._active_tasks` EN ENTIER, tous
           pools confondus (voir `_ActiveTask.pool`) : une tâche "Outils"
           qui écrit dans Mods/ (ex: Compat. Framework) doit rester
           mutuellement exclusive avec une tâche "Tâches" qui écrit aussi
           dans Mods/ (ex: Extraire vers Mods/), même si elles logguent
           dans deux consoles différentes.
        """
        conflict = _resource_conflict(
            [task.resource_tags for task in self._active_tasks.values()], resource_tags
        )
        if conflict:
            _, main_write = self._main_console_for_pool(pool)
            main_write(
                f"[#D8C091]« {title} » différée : {', '.join(sorted(conflict))} "
                f"déjà utilisé(e) par une tâche en cours — relance une fois "
                f"celle-ci terminée.[/#D8C091]"
            )
            return

        log, write, tab_id = self._acquire_task_console(title, pool)
        worker = launch(log)
        if worker is not None:
            self._active_tasks[worker] = _ActiveTask(
                resource_tags=resource_tags, tab_id=tab_id, write=write, pool=pool
            )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Libère la réservation de ressources d'une tâche "Tâches" dès que
        son `Worker` associé se termine (voir `_start_task`), et journalise
        toute erreur de worker : tous les `@work` de cet écran sont
        `exit_on_error=False` (une erreur ne doit plus faire planter tout le
        TUI — voir `bg3_mod_tui.crash_log`), donc Textual ne la remonte plus
        jamais à `App._handle_exception` de lui-même ; c'est ce hook qui
        prend le relais pour qu'elle reste tracée (crash log horodaté) ET
        visible pour l'utilisateur (message dans la console concernée).

        Pour un worker géré par `_start_task` (dans `self._active_tasks`),
        le message va dans SA console (`_ActiveTask.write`) plutôt que dans
        l'onglet "Tâches" principal par défaut. Pour un worker non tracké
        (ex: "Lancer un outil...", "Optimiser le préfixe...") qui n'a pas
        déjà son propre `try/except` autour d'une erreur attendue, le
        message va dans la console d'outils (`#tools-log`)."""
        if event.worker.state == WorkerState.ERROR and event.worker.error is not None:
            log_crash(event.worker.error)
            task = self._active_tasks.get(event.worker)
            report = task.write if task is not None else self._tool_log
            report(f"[#C46F6F]Erreur inattendue : {event.worker.error}[/#C46F6F]")

        if not event.worker.is_finished:
            return
        self._active_tasks.pop(event.worker, None)

    def _log(self, message: str) -> None:
        self.query_one("#actions-log", ConsoleLog).write(message)
        self._mark_log_tab_active("actions-log-tab")

    def _tool_log(self, message: str) -> None:
        self.query_one("#tools-log", ConsoleLog).write(message)
        self._mark_log_tab_active("tools-log-tab")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Hook générique de suivi d'usage (sous-tâche "Compteur
        d'utilisation par bouton/outil/profil", voir `usage_stats.py`) et de
        déclenchement des quick actions (sous-tâche "3 actions les plus
        utilisées en boutons quick-action", voir `_refresh_quick_actions`) :
        incrémente le compteur persistant de CHAQUE bouton d'action réel
        (id `action-*`, hors `_UNTRACKED_ACTION_ID`) et relance un clic sur
        le bouton original quand c'est une quick action (id `quick-*`) qui
        a été pressée — sans dupliquer les ~30 handlers
        `@on(Button.Pressed, "#action-xxx")` déjà en place un par un, et
        sans dupliquer leur logique pour les quick actions.

        Choix délibéré plutôt qu'un décorateur à ajouter sur chacun d'eux :
        Textual invoque, pour un même widget, TOUS les handlers qui
        correspondent à un message donné — les méthodes décorées `@on`
        (sélecteur par sélecteur) ET la méthode "par convention de nommage"
        `on_<event>` — indépendamment les unes des autres (voir
        `MessagePump._get_dispatch_methods`/`_on_message` dans
        `textual.message_pump`, vérifié dans les sources de la version
        installée). Cette méthode ne fait donc jamais `event.stop()` ni
        `event.prevent_default()` : même si elle le faisait, ça n'empêche
        ni le déclenchement des autres handlers de CE widget (déjà
        déterminé avant l'appel), ni celui du handler spécifique de
        l'action pressée — seule la PROPAGATION vers un widget parent
        serait coupée, ce qui n'a aucune incidence ici (aucun handler ne
        fait remonter l'événement plus haut que `ActionsScreen`). Risque de
        régression donc nul sur les handlers existants.

        Pour une quick action, `Button.press()` sur le bouton original
        poste un NOUVEAU `Button.Pressed` (id `action-*`) qui repasse par ce
        même hook : le clic est donc compté une seule fois (sur l'id
        original, pas sur `quick-*`) et déclenche le handler spécifique
        normalement, sans logique dupliquée ici."""
        button_id = event.button.id or ""

        if button_id.startswith("quick-"):
            original_id = button_id.removeprefix("quick-")
            try:
                self.query_one(f"#{original_id}", Button).press()
            except Exception:
                pass
            return

        if not button_id.startswith("action-") or button_id == self._UNTRACKED_ACTION_ID:
            return
        increment_usage_stat(
            self._config.profiles_dir, self._config.active_profile, button_id
        )
        self.run_worker(self._refresh_quick_actions(), exclusive=True, group="refresh-quick-actions")

    def on_mount(self) -> None:
        self.run_worker(self._refresh_quick_actions(), exclusive=True, group="refresh-quick-actions")

    def _action_button_lookup(self) -> dict[str, Button]:
        """Ids -> bouton d'action original (`action-*`, hors
        `_UNTRACKED_ACTION_ID`), pour retrouver leur libellé/tooltip lors de
        la construction des quick actions sans dupliquer les ~30
        définitions de `compose()`."""
        return {
            button.id: button
            for button in self.query("#menu-buttons Button")
            if button.id and button.id.startswith("action-") and button.id != self._UNTRACKED_ACTION_ID
        }

    async def _refresh_quick_actions(self) -> None:
        """(Re)construit la barre de quick actions (les 3 boutons d'action
        les plus utilisés pour le profil actif — voir `usage_stats.top_actions`)
        en haut de l'écran. Appelée au montage de l'écran (`on_mount`) ET
        après chaque incrément d'usage (`on_button_pressed`) : recalcul en
        temps réel plutôt que seulement au prochain lancement, plus simple
        à obtenir ici qu'il n'y paraît puisqu'il suffit de démonter/remonter
        les 0 à 3 boutons de cette petite barre dédiée (pas de mise en page
        complexe à recalculer).

        Chaque quick action clone juste le libellé/tooltip du bouton
        original (id `quick-<id_original>`) — aucune logique dupliquée, le
        clic est redirigé vers le bouton original par `on_button_pressed`
        ci-dessus."""
        bar = self.query_one("#quick-actions-bar")
        # `remove()` est asynchrone (retourne un `AwaitRemove`) : il FAUT
        # attendre que les anciens boutons soient réellement retirés du DOM
        # avant de remonter les nouveaux, sinon `bar.mount(...)` plus bas
        # peut tenter de créer un bouton avec le même id qu'un ancien pas
        # encore supprimé et lever `DuplicateIds` (crash reproductible à
        # chaque incrément d'usage tant qu'un top 3 était déjà affiché).
        await bar.query(Button).remove()

        lookup = self._action_button_lookup()
        stats = load_usage_stats(self._config.profiles_dir, self._config.active_profile)
        top_ids = [button_id for button_id in top_actions(stats) if button_id in lookup]

        bar.display = bool(top_ids)
        for button_id in top_ids:
            original = lookup[button_id]
            bar.mount(
                Button(
                    str(original.label),
                    id=f"quick-{button_id}",
                    tooltip=original.tooltip,
                )
            )

    @on(Button.Pressed, "#action-download-mods")
    def handle_download_mods(self) -> None:
        # Touche archives_dir/_installees/_a_traiter (téléchargement +
        # nettoyage des doublons en préambule) : incompatible avec
        # `run_extract`, qui déplace/nettoie ces mêmes dossiers.
        self._start_task(
            title="Télécharger les mods",
            resource_tags=frozenset({"archives"}),
            launch=self.run_download_mods,
        )

    def _select_nexus_files(
        self, mod_id: int, mod_name: str, candidates: list[tuple[int, str]]
    ) -> list[int]:
        """Appelé depuis le thread de téléchargement (voir
        `run_download_mods`) : bascule sur le thread principal pour
        afficher `NexusFileSelectionScreen` et bloque jusqu'à validation."""
        done = threading.Event()
        result: list[int] = []

        def show_screen() -> None:
            def on_result(chosen: list[int]) -> None:
                result.extend(chosen)
                done.set()
            self.app.push_screen(NexusFileSelectionScreen(mod_id, mod_name, candidates), on_result)

        self.app.call_from_thread(show_screen)
        done.wait()
        return result

    def _on_download_progress(
        self, slot_id: str, label: str, downloaded: int | None, total: int | None
    ) -> None:
        """Callback `on_download_progress` (voir `mod_pipeline.DownloadProgressFn`)
        passé à `download_mods_from_links_file`/`download_subscribed_modio_mods` :
        appelé DIRECTEMENT depuis un thread de téléchargement du pool (Nexus
        ou mod.io, potentiellement plusieurs à la fois) — bascule sur le
        thread UI avant de toucher au widget, comme le reste des callbacks
        de progression de cet écran (ex: `_log`)."""
        self.app.call_from_thread(
            self.query_one("#downloads-progress", DownloadProgressConsole).update_progress,
            slot_id,
            label,
            downloaded,
            total,
        )
        self.app.call_from_thread(self._mark_log_tab_active, "downloads-log-tab")

    def _select_nested_archives(self, archive_name: str, candidates: list[Path]) -> list[Path]:
        """Appelé depuis le thread d'extraction (voir `run_extract`) :
        bascule sur le thread principal pour afficher
        `NestedArchiveSelectionScreen` et bloque jusqu'à validation."""
        done = threading.Event()
        result: list[Path] = []

        def show_screen() -> None:
            def on_result(chosen: list[Path]) -> None:
                result.extend(chosen)
                done.set()
            self.app.push_screen(NestedArchiveSelectionScreen(archive_name, candidates), on_result)

        self.app.call_from_thread(show_screen)
        done.wait()
        return result

    def _cleanup_duplicate_archives(self, log) -> None:
        """Nettoie les doublons d'archives déjà présents dans
        `_installees`/`_a_traiter` (voir
        `mod_pipeline.cleanup_duplicate_archives`) — appelé en préambule
        de "télécharger les mods" et "extraire vers Mods/" pour que ce
        nettoyage se fasse automatiquement à chaque exécution plutôt que
        d'être une action séparée à lancer soi-même."""
        log("=== Nettoyage des doublons d'archives déjà présents ===")
        total_removed = 0
        total_freed = 0
        for directory in (
            self._config.archives_installed_dir,
            self._config.archives_pending_dir,
        ):
            report = cleanup_duplicate_archives(directory, log=log)
            total_removed += len(report["removed"])
            total_freed += report["freed_bytes"]
        if total_removed:
            log(
                f"{total_removed} doublon(s) supprimé(s) au total "
                f"({_human_size(total_freed)} récupéré(s))."
            )

    @work(exclusive=True, thread=True, group="run_download_mods", exit_on_error=False)
    def run_download_mods(self, log: Callable[[str], None]) -> None:
        self.app.call_from_thread(
            self.query_one("#downloads-progress", DownloadProgressConsole).clear
        )

        self._cleanup_duplicate_archives(log)

        log("=== Téléchargement des mods listés dans nexus_links_to_add.md (Nexus) ===")
        try:
            client = NexusClient(os.environ.get("NEXUS_API_KEY", ""))
            report = download_mods_from_links_file(
                client,
                self._config.nexus_links_file,
                self._config.archives_dir,
                archives_installed_dir=self._config.archives_installed_dir,
                archives_pending_dir=self._config.archives_pending_dir,
                profiles_dir=self._config.profiles_dir,
                profile_name=self._config.active_profile,
                select_files=self._select_nexus_files,
                on_download_progress=self._on_download_progress,
                log=log,
            )
            log(
                f"Terminé (Nexus) : {len(report['downloaded'])} téléchargé(s), "
                f"{len(report['skipped'])} déjà présent(s), "
                f"{len(report['failed'])} échec(s)."
            )
        except NexusAPIError as exc:
            log(f"[#C46F6F]Erreur (Nexus) : {exc}[/#C46F6F]")
        except Exception as exc:
            log(f"[#C46F6F]Erreur inattendue (Nexus) : {exc}[/#C46F6F]")

        log("=== Récupération des mods abonnés sur mod.io ===")
        try:
            client = ModIOClient(
                api_key=os.environ.get("MODIO_API_KEY", ""),
                user_id=os.environ.get("MOD_IO_USER_ID") or None,
                api_base=os.environ.get("MODIO_API_BASE") or None,
                access_token=os.environ.get("MODIO_ACCESS_TOKEN") or None,
            )
            report = download_subscribed_modio_mods(
                client,
                self._config.archives_dir,
                archives_installed_dir=self._config.archives_installed_dir,
                archives_pending_dir=self._config.archives_pending_dir,
                on_download_progress=self._on_download_progress,
                log=log,
            )
            log(
                f"Terminé (mod.io) : {len(report['downloaded'])} téléchargé(s), "
                f"{len(report['skipped'])} déjà présent(s), "
                f"{len(report['failed'])} échec(s)."
            )
        except ModIOAPIError as exc:
            log(f"[#C46F6F]Erreur (mod.io) : {exc}[/#C46F6F]")
        except Exception as exc:
            log(f"[#C46F6F]Erreur inattendue (mod.io) : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-clean-paks")
    def handle_clean_paks(self) -> None:
        # Supprime les .pak de Mods/ et les mods DLL déployés : incompatible
        # avec toute autre action qui écrit dans ces mêmes dossiers.
        self._start_task(
            title="Nettoyer les .pak",
            resource_tags=frozenset({"mods-dir", "native-mods"}),
            launch=self.run_clean_paks,
        )

    @work(exclusive=True, thread=True, group="run_clean_paks", exit_on_error=False)
    def run_clean_paks(self, log: Callable[[str], None]) -> None:
        log("=== Nettoyage des .pak de Mods/ ===")
        clean_pak_files(
            self._config.managed_mods_link,
            native_mods_managed_dir=self._config.native_mods_managed_dir,
            log=log,
        )

    @on(Button.Pressed, "#action-sync-modsettings")
    def handle_sync_modsettings(self) -> None:
        # Relit Mods/ pour recalculer l'ordre de charge et écrit
        # modsettings.lsx : incompatible avec toute action qui restructure
        # Mods/ pendant la lecture, ou qui écrit modsettings.lsx.
        self._start_task(
            title="Sync. modsettings.lsx",
            resource_tags=frozenset({"mods-dir", "modsettings"}),
            launch=self.run_sync_modsettings,
        )

    @work(exclusive=True, thread=True, group="run_sync_modsettings", exit_on_error=False)
    def run_sync_modsettings(self, log: Callable[[str], None]) -> None:
        log("=== Synchronisation de modsettings.lsx ===")
        try:
            report = setup_links(self._config)
            for step in report.steps:
                log(step)
        except LinkingError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-extract")
    def handle_extract(self) -> None:
        # Nettoie/déplace des archives (comme le téléchargement) ET écrit
        # dans Mods/, DataMods/, Data/ (comme le nettoyage/déploiement de
        # mods DLL) : incompatible avec toutes les actions qui touchent
        # l'un ou l'autre.
        self._start_task(
            title="Extraire vers Mods/",
            resource_tags=frozenset({"mods-dir", "archives", "native-mods"}),
            launch=self.run_extract,
        )

    @work(exclusive=True, thread=True, group="run_extract", exit_on_error=False)
    def run_extract(self, log: Callable[[str], None]) -> None:
        self._cleanup_duplicate_archives(log)

        log("=== Extraction des archives vers Mods/ ===")
        report = extract_archives_to_mods(
            self._config.archives_dir,
            self._config.managed_mods_link,
            self._config.archives_pending_dir,
            self._config.archives_installed_dir,
            loose_mods_dir=self._config.loose_mods_managed_dir,
            game_data_dir=self._config.game_data_dir,
            native_mods_manifest_path=self._config.native_mods_manifest_file,
            native_mods_managed_dir=self._config.native_mods_managed_dir,
            managed_dir=self._config.managed_dir,
            select_nested_archives=self._select_nested_archives,
            log=log,
        )
        log(
            f"Terminé : {len(report['installed'])} installée(s), "
            f"{len(report['pending'])} à traiter manuellement, "
            f"{len(report['skipped'])} ignorée(s) (.pak déjà présent(s)), "
            f"{len(report['failed'])} échec(s)."
        )

    @on(Button.Pressed, "#action-native-mods")
    def handle_native_mods(self) -> None:
        # Lit archives (_a_traiter/_installees) et écrit dans le dossier
        # géré des mods DLL : incompatible avec les actions qui écrivent
        # dans l'un ou l'autre.
        self._start_task(
            title="Déployer mods DLL",
            resource_tags=frozenset({"native-mods", "archives"}),
            launch=self.run_native_mods,
        )

    @work(exclusive=True, thread=True, group="run_native_mods", exit_on_error=False)
    def run_native_mods(self, log: Callable[[str], None]) -> None:
        log("=== Déploiement des mods DLL (manifest natif) ===")
        try:
            report = deploy_native_mods_from_manifest(
                pending_dir=self._config.archives_pending_dir,
                installed_dir=self._config.archives_installed_dir,
                managed_native_dir=self._config.native_mods_managed_dir,
                managed_dir=self._config.managed_dir,
                manifest_path=self._config.native_mods_manifest_file,
                log=log,
            )
        except NativeModsManifestError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return
        log(
            f"Terminé : {len(report['deployed'])} déployé(s) cette fois-ci, "
            f"{len(report['skipped'])} ignoré(s) (déjà déployé ou pas encore téléchargé "
            f"— voir le détail ci-dessus), {len(report['failed'])} échec(s)."
        )

    def _download_tools_task(self, log: Callable[[str], None]) -> bool:
        """Corps effectif de la MAJ des outils — factorisé (même principe
        que `_restore_profile_task`) pour être appelé par `run_update_all`
        en première étape de la séquence unifiée (l'ancien bouton dédié
        "MAJ des outils" et son worker `run_download_tools` ont été retirés,
        `run_update_all` les enchaînant déjà tous — voir TODO section 9b).
        Retourne `True` en cas de succès, `False` sinon (utilisé par
        `run_update_all` pour décider d'enchaîner ou d'arrêter la
        séquence)."""
        log("=== Téléchargement/mise à jour des outils (TOOLS.md) ===")
        try:
            entries = parse_tools_table(self._config.tools_md_file)
        except ToolsError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return False
        try:
            for entry in entries:
                download_and_extract_tool(
                    entry, self._config.project_root, log=log)

            log("--- Déploiement des DLL dans le jeu (bin/) ---")
            deploy_native_mod_loader(
                self._config.tools_dir, self._config.game_bin_dir, log=log)
            deploy_script_extender(self._config.tools_dir,
                                   self._config.game_bin_dir, log=log)
        except Exception as exc:
            log(f"[#C46F6F]Erreur inattendue : {exc}[/#C46F6F]")
            return False
        log("Terminé.")
        return True

    def _build_compat_framework_task(self, log: Callable[[str], None]) -> bool:
        """Corps effectif de la compilation de Compat. Framework —
        factorisé pour être appelé par `run_update_all` (2ème étape de la
        séquence unifiée ; l'ancien bouton dédié "Compiler Compat.
        Framework" et son worker `run_build_compat_framework` ont été
        retirés, voir TODO section 9b). Retourne `True`/`False` selon le
        succès (voir `_download_tools_task`)."""
        log("=== Compilation de BG3 Compatibility Framework (Divine.exe) ===")
        try:
            build_compat_framework_pak(
                self._config.tools_dir,
                self._config.managed_mods_link,
                reference_path=self._config.appdata_path,
                log=log,
            )
        except CompatibilityFrameworkError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return False
        return True

    def _build_mod_fixer_fork_task(self, log: Callable[[str], None]) -> bool:
        """Corps effectif du fork de Mod Fixer — factorisé pour être
        appelé par `run_update_all` (3ème et dernière étape de la séquence
        unifiée ; l'ancien bouton dédié "Forker Mod Fixer" et son worker
        `run_build_mod_fixer_fork` ont été retirés, voir TODO section 9b).
        Retourne `True`/`False` selon le succès (voir
        `_download_tools_task`)."""
        log("=== Fork de Mod Fixer avec meta.lsx (Divine.exe) ===")
        try:
            build_mod_fixer_fork(
                self._config.managed_mods_link,
                self._config.tools_dir,
                reference_path=self._config.appdata_path,
                log=log,
            )
        except ModFixerForkError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return False
        return True

    @on(Button.Pressed, "#action-update-all")
    def handle_update_all(self) -> None:
        # Enchaîne les 3 étapes ci-dessus dans l'ordre (MAJ des outils ->
        # Compat. Framework -> Mod Fixer Fork) : mêmes ressources qu'elles
        # cumulent toutes les 3, pour que le verrouillage empêche aussi bien
        # une des 3 actions individuelles qu'une autre exécution de la
        # séquence complète de démarrer en même temps.
        self._start_task(
            title="Tout mettre à jour (outils + Compat Framework + Mod Fixer)",
            resource_tags=frozenset({"tools-dir", "game-bin-dir", "mods-dir"}),
            launch=self.run_update_all,
            pool="tools",
        )

    @work(exclusive=True, thread=True, group="run_update_all", exit_on_error=False)
    def run_update_all(self, log: Callable[[str], None]) -> None:
        """Enchaîne dans l'ordre les 3 étapes "MAJ des outils" -> "Compiler
        Compat. Framework" -> "Forker Mod Fixer", en réutilisant leurs
        méthodes `_*_task` déjà factorisées (aucune logique dupliquée). La
        progression "[i/3]" et l'arrêt à la première étape en échec sont
        délégués à `_run_task_sequence` (fonction module-level, voir son
        docstring pour le choix de s'arrêter plutôt que d'enchaîner coûte
        que coûte — les étapes 2 et 3 dépendent explicitement de Divine.exe
        téléchargé par la 1ère)."""
        steps: list[tuple[str, Callable[[Callable[[str], None]], bool]]] = [
            ("MAJ des outils", self._download_tools_task),
            ("Compiler Compat. Framework", self._build_compat_framework_task),
            ("Forker Mod Fixer", self._build_mod_fixer_fork_task),
        ]
        _run_task_sequence(steps, log)

    @on(Button.Pressed, "#action-launch-tool")
    def handle_launch_tool(self) -> None:
        executables = find_executables(self._config.tools_dir)
        if not executables:
            self._tool_log(
                "[#D8C091]Aucun exécutable trouvé sous Tools/.[/#D8C091]")
            return

        def on_picked(exe_path: Path | None) -> None:
            if exe_path is None:
                return
            # Sous-tâche 7d : passe par `_start_task` (pool "tools") plutôt
            # que d'appeler `run_launch_tool` directement, pour que deux
            # lancements simultanés (le worker reste `exclusive=False`,
            # plusieurs outils peuvent tourner en parallèle) obtiennent
            # chacun leur propre onglet dynamique sous "Outils" au lieu
            # d'entrelacer leurs sorties dans `#tools-log`.
            self._start_task(
                title=f"Lancer {exe_path.name}",
                resource_tags=frozenset(),
                launch=lambda log: self.run_launch_tool(exe_path, log),
                pool="tools",
            )

        self.app.push_screen(ToolPickerScreen(
            executables, self._config.project_root), on_picked)

    @work(exclusive=False, thread=True, exit_on_error=False)
    def run_launch_tool(self, exe_path: Path, log: Callable[[str], None]) -> None:
        log_dir = self._config.logs_dir
        try:
            launch_tool(
                exe_path, reference_path=self._config.appdata_path, log_dir=log_dir)
            log(f"Lancé : {exe_path.name} (sortie journalisée dans {log_dir / (exe_path.stem + '.log')})")
        except LauncherError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-class-builder")
    def handle_class_builder(self) -> None:
        # Bouton désactivé dans compose() tant que le serveur Web ne tourne
        # pas (voir _start_web_server/_stop_web_server) : le clic ne peut
        # normalement survenir que serveur démarré, ce garde-fou n'est là
        # que pour rester correct si l'état venait à diverger. Génération +
        # écriture quasi instantanées (gabarit HTML en mémoire, aucun
        # réseau/sous-processus) : pas besoin d'un worker `thread=True` ici.
        if self._web_server_handle is None or not self._web_server_handle.is_running:
            self._tool_log(
                "[#D8C091]Démarre d'abord le serveur Web (bouton planète) pour "
                "afficher le build de classes.[/#D8C091]"
            )
            return
        try:
            write_html(self._config.web_root_dir / DEFAULT_HTML_FILENAME)
            url = self._web_base_url() + DEFAULT_HTML_FILENAME
            webbrowser.open(url)
            self._tool_log(f"Build de classes généré et ouvert : {url}")
        except OSError as exc:
            self._tool_log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-se-console")
    def handle_script_extender_console(self) -> None:
        # Sous-tâche 11a du TODO : lecture seule, ouvre un terminal externe
        # dédié (voir `terminal_launcher.open_in_terminal`) qui tail -F les
        # logs BG3SE — jamais un widget intégré au TUI ni d'écriture de
        # commande vers le jeu (11b/11c hors scope).
        self._start_task(
            title="Console Script Extender",
            resource_tags=frozenset(),
            launch=self.run_script_extender_console,
            pool="tools",
        )

    @work(exclusive=False, thread=True, exit_on_error=False)
    def run_script_extender_console(self, log: Callable[[str], None]) -> None:
        log_dir = find_osiris_log_dir(self._config.appdata_path)
        if log_dir is None:
            log(
                "[#C46F6F]Impossible de localiser le dossier de logs BG3SE : "
                "préfixe Proton introuvable à partir de "
                f"{self._config.appdata_path}.[/#C46F6F]"
            )
            return

        command = build_tail_command(log_dir)
        if open_in_terminal(command):
            log(
                "Terminal externe ouvert : suit en direct "
                f"{log_dir} (nécessite EnableLogging=true dans "
                "ScriptExtenderSettings.json et le jeu lancé — la console "
                "attend elle-même l'apparition des logs sinon)."
            )
        else:
            log(
                "[#D8C091]Aucun terminal externe disponible (pas d'affichage "
                "ou émulateur introuvable). Dossier de logs BG3SE attendu : "
                f"{log_dir}[/#D8C091]"
            )

    @on(Button.Pressed, "#action-protontricks")
    def handle_protontricks(self) -> None:
        # Sous-tâche 7d : onglet dynamique "Outils" dédié si un autre outil
        # (ou un autre protontricks) tourne déjà — voir `handle_launch_tool`.
        self._start_task(
            title="Ouvrir protontricks",
            resource_tags=frozenset(),
            launch=self.run_protontricks,
            pool="tools",
        )

    @work(exclusive=False, thread=True, exit_on_error=False)
    def run_protontricks(self, log: Callable[[str], None]) -> None:
        log_dir = self._config.logs_dir
        try:
            open_protontricks(self._config.appdata_path, log_dir=log_dir)
            log(
                f"protontricks ouvert (préfixe BG3, sortie journalisée dans {log_dir / 'protontricks.log'}).")
        except LauncherError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-inventory")
    def handle_inventory(self) -> None:
        # Lecture seule de Mods/ et des archives, écrit uniquement son
        # propre fichier (inventory.json) : peut tourner aux côtés de
        # n'importe quelle autre tâche (l'inventaire reflètera juste l'état
        # au moment du scan, ce qui est acceptable pour un rapport).
        self._start_task(
            title="Inventaire des mods",
            resource_tags=frozenset(),
            launch=self.run_inventory,
        )

    @work(exclusive=True, thread=True, group="run_inventory", exit_on_error=False)
    def run_inventory(self, log: Callable[[str], None]) -> None:
        log("=== Génération de l'inventaire des mods ===")
        try:
            inventory = build_inventory(
                mods_dir=self._config.managed_mods_link,
                archives_dir=self._config.archives_dir,
                archives_installed_dir=self._config.archives_installed_dir,
                archives_pending_dir=self._config.archives_pending_dir,
                on_progress=log,
            )
            save_inventory(inventory, self._config.inventory_file)
        except OSError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return
        counts = inventory["counts"]
        log(
            f"{counts['paks']} .pak, {counts['archives']} archive(s) "
            f"({counts['archives_with_nexus_id']} avec ID Nexus identifié) "
            f"-> {self._config.inventory_file}"
        )

    @on(Button.Pressed, "#action-orphaned-archives")
    def handle_orphaned_archives(self) -> None:
        # Même raisonnement que "Inventaire des mods" : lecture seule des
        # .pak déployés/archives, écrit son propre rapport
        # (archives_orphelines.md).
        self._start_task(
            title="Archives orphelines...",
            resource_tags=frozenset(),
            launch=self.run_orphaned_archives,
        )

    @work(exclusive=True, thread=True, group="run_orphaned_archives", exit_on_error=False)
    def run_orphaned_archives(self, log: Callable[[str], None]) -> None:
        log("=== Recherche des archives orphelines (_installees) ===")
        try:
            inventory = build_inventory(
                mods_dir=self._config.managed_mods_link,
                archives_dir=self._config.archives_dir,
                archives_installed_dir=self._config.archives_installed_dir,
                archives_pending_dir=self._config.archives_pending_dir,
                on_progress=log,
            )
            save_inventory(inventory, self._config.inventory_file)
        except OSError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return

        try:
            native_manifest = load_native_mods_manifest(self._config.native_mods_manifest_file)
        except NativeModsManifestError as exc:
            log(f"[#D8C091]Manifeste des mods natifs ignoré : {exc}[/#D8C091]")
            native_manifest = {}

        candidates = find_orphaned_archives(inventory, native_manifest)
        if not candidates:
            log("Aucune archive orpheline : chaque archive de _installees correspond à un .pak/DLL actuellement déployé.")
            return

        divine_exe = find_divine_exe(self._config.tools_dir)
        if divine_exe is None:
            log(
                f"[#D8C091]Divine.exe introuvable sous Tools/ExportTools/ — "
                f"télécharge d'abord LSLib via « MAJ des outils » pour vérifier "
                f"ces {len(candidates)} candidat(e)s par UUID plutôt que par nom "
                f"seul (peu fiable, voir tooltip).[/#D8C091]"
            )
            self._write_orphans_report(candidates, verified=False, log=log)
            return

        log(
            f"{len(candidates)} candidat(e)s d'après le nom de fichier (peu "
            f"fiable) — vérification par UUID réel du .pak (via Divine.exe) "
            f"pour écarter les faux positifs. Ça va prendre un moment..."
        )

        pak_paths = sorted(self._config.managed_mods_link.glob("*.pak"))
        log(f"Lecture de l'UUID de {len(pak_paths)} .pak actuellement déployé(s)...")
        deployed_uuids = build_deployed_uuid_index(
            pak_paths,
            divine_exe=divine_exe,
            reference_path=self._config.project_root,
            log=log,
        )

        report_dir = profile_data_dir(self._config.profiles_dir, self._config.active_profile)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "archives_orphelines.md"

        confirmed: list[dict] = []
        unverifiable: list[dict] = []
        processed: list[tuple[dict, str]] = []
        total_candidates = len(candidates)
        # Un par un si peu de candidats, sinon un intervalle qui garde des
        # mises à jour fréquentes sans spammer sur un gros lot (même logique
        # que build_deployed_uuid_index ci-dessus).
        step = 1 if total_candidates <= 20 else 10
        for index, archive in enumerate(candidates, start=1):
            if index % step == 1 or step == 1 or index == total_candidates:
                log(f"  [{index}/{total_candidates}] {archive['file']}...")
            archive_path = self._config.archives_installed_dir / archive["file"]
            identities = archive_pak_identities(
                archive_path,
                divine_exe=divine_exe,
                reference_path=self._config.project_root,
                log=log,
            )
            if not identities:
                # Pas de .pak dedans (mod "loose files") ou lecture échouée :
                # la méthode par UUID ne s'applique pas, on ne peut pas
                # confirmer — gardé à part plutôt que déclaré orphelin à tort.
                unverifiable.append(archive)
                statut = "non vérifiable (pas de .pak dans l'archive)"
            elif not any(uuid in deployed_uuids for uuid, _name in identities):
                confirmed.append(archive)
                statut = "orpheline confirmée (UUID absent des .pak déployés)"
            else:
                statut = "faux positif écarté (mod toujours déployé)"
            processed.append((archive, statut))
            # Flush à chaque étape plutôt qu'un seul écrit final : chaque
            # appel à Divine.exe est lent (un sous-processus par archive), un
            # gros lot peut prendre plusieurs minutes — une interruption en
            # cours de route (fermeture de l'app, crash) laisse ainsi un
            # rapport partiel avec les décisions déjà prises, au lieu de rien.
            self._flush_orphans_progress(
                report_path, processed, done=index, total=total_candidates
            )

        discarded = len(candidates) - len(confirmed) - len(unverifiable)
        log(
            f"Vérification terminée : {len(confirmed)} orpheline(s) confirmée(s), "
            f"{discarded} faux positif(s) écarté(s) (mod toujours déployé, même "
            f"nom de fichier différent), {len(unverifiable)} non vérifiable(s) "
            f"(pas de .pak dedans)."
        )
        self._write_orphans_report(confirmed, verified=True, unverifiable=unverifiable, log=log)

    def _flush_orphans_progress(
        self,
        report_path: Path,
        processed: list[tuple[dict, str]],
        *,
        done: int,
        total: int,
    ) -> None:
        """Réécrit `archives_orphelines.md` avec l'état accumulé jusqu'ici
        (une ligne par archive déjà traitée, avec son statut). Réécriture
        complète du fichier à chaque étape plutôt qu'un simple append :
        plus de réécritures disque, mais pour un lot de quelques
        dizaines/centaines d'archives au pire, c'est négligeable — et ça
        évite de maintenir deux formats différents (un « brut » en append,
        un « poli » à la fin) : la version finale, écrite par
        `_write_orphans_report` une fois la vérification terminée, remplace
        simplement ce rapport de progression par un regroupement par statut
        plus lisible."""
        lines = [
            "# Archives potentiellement orphelines\n",
            (
                f"Vérification par UUID réel (Divine.exe) en cours : "
                f"{done}/{total} archive(s) traitée(s). Rapport mis à jour "
                f"au fil de l'eau — une interruption ne perd pas les "
                f"décisions déjà prises ci-dessous.\n"
            ),
            "| Archive | Taille | Origine | Modifiée | Statut |",
            "|---|---|---|---|---|",
        ]
        lines += [_orphan_report_row(archive, statut) for archive, statut in processed]
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_orphans_report(
        self,
        orphans: list[dict],
        *,
        verified: bool,
        unverifiable: list[dict] | None = None,
        log: Callable[[str], None],
    ) -> None:
        if not orphans and not unverifiable:
            log("Aucune archive orpheline confirmée.")
            return

        def _table(archives: list[dict]) -> list[str]:
            rows = [
                "| Archive | Taille | Origine | Modifiée |",
                "|---|---|---|---|",
            ]
            for archive in sorted(archives, key=lambda a: a["size_bytes"], reverse=True):
                origin = (
                    f"[{archive['mod_name_guess']}]({archive['nexus_url']})"
                    if archive.get("nexus_url")
                    else (archive.get("mod_name_guess") or "?")
                )
                rows.append(
                    f"| {archive['file']} | {_human_size(archive['size_bytes'])} | "
                    f"{origin} | {archive['modified'][:10]} |"
                )
            return rows

        total_bytes = sum(a["size_bytes"] for a in orphans)
        lines = ["# Archives potentiellement orphelines\n"]
        if verified:
            lines.append(
                f"{len(orphans)} archive(s) confirmée(s) orpheline(s) par UUID "
                f"réel du .pak (Divine.exe) : aucun .pak actuellement déployé "
                f"ne partage l'UUID de celui contenu dans l'archive — "
                f"{_human_size(total_bytes)} à potentiellement récupérer.\n"
            )
        else:
            lines.append(
                f"{len(orphans)} archive(s) dans `_installees` sans .pak/DLL "
                f"actuellement déployé correspondant ({_human_size(total_bytes)} au total).\n\n"
                "Association par **nom de fichier** seulement (Divine.exe "
                "indisponible pour vérifier par UUID réel) — best-effort, pas "
                "une liste garantie sans faux positif : à vérifier avant "
                "suppression, voir `inventory.find_orphaned_archives`.\n"
            )
        lines += _table(orphans)

        if unverifiable:
            lines += [
                "\n## Non vérifiables (pas de .pak dans l'archive)\n",
                (
                    "Mods \"loose files\" ou mods natifs sans entrée dans "
                    "`native_mods_manifest.json` — la vérification par UUID ne "
                    "s'applique qu'aux .pak, à vérifier manuellement.\n"
                ),
            ]
            lines += _table(unverifiable)

        report_dir = profile_data_dir(self._config.profiles_dir, self._config.active_profile)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "archives_orphelines.md"
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log(
            f"{len(orphans)} archive(s) orpheline(s)"
            f"{' confirmée(s) par UUID' if verified else ''} "
            f"({_human_size(total_bytes)}) -> {report_path}"
        )

    @on(Button.Pressed, "#action-orphan-paks")
    def handle_resolve_pak_origins(self) -> None:
        # Lecture seule de Mods/ et des archives ; n'écrit que le petit
        # fichier d'origines manuelles propre au profil actif (via
        # `save_manual_origin`, dans `_prompt_manual_pak_origins`) — pas
        # Mods/ lui-même.
        self._start_task(
            title="Origine des .pak isolés...",
            resource_tags=frozenset(),
            launch=self.run_resolve_pak_origins,
        )

    @work(exclusive=True, thread=True, group="run_resolve_pak_origins", exit_on_error=False)
    def run_resolve_pak_origins(self, log: Callable[[str], None]) -> None:
        """Enchaîne les trois mécanismes de `pak_origin` sur les .pak
        isolés de Mods/ (voir le docstring de ce module) : nom, puis UUID
        réel, puis — en dernier recours — un lien saisi par l'utilisateur
        (mémorisé ensuite via `save_manual_origin`)."""
        log("=== Origine des .pak isolés ===")
        try:
            inventory = build_inventory(
                mods_dir=self._config.managed_mods_link,
                archives_dir=self._config.archives_dir,
                archives_installed_dir=self._config.archives_installed_dir,
                archives_pending_dir=self._config.archives_pending_dir,
                on_progress=log,
            )
        except OSError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return

        orphans = find_orphaned_paks(inventory["paks"])
        if not orphans:
            log("Aucun .pak isolé : chaque .pak de Mods/ est associé à une archive connue.")
            return

        manual_origins = load_manual_origins(self._config.profiles_dir, self._config.active_profile)
        archives = scan_all_archives(
            archives_dir=self._config.archives_dir,
            archives_installed_dir=self._config.archives_installed_dir,
            archives_pending_dir=self._config.archives_pending_dir,
            on_progress=log,
        )
        divine_exe = find_divine_exe(self._config.tools_dir)
        if divine_exe is None:
            log(
                "[#D8C091]Divine.exe introuvable sous Tools/ExportTools/ — étape 2 "
                "(matching par UUID) ignorée, seuls le nom et la saisie manuelle "
                "seront tentés.[/#D8C091]"
            )

        resolved_by_name = 0
        resolved_by_uuid = 0
        already_manual = 0
        unresolved: list[dict] = []

        for pak in orphans:
            pak_file = pak["file"]
            if pak_file in manual_origins:
                already_manual += 1
                continue

            match = match_orphan_by_name(pak_file, archives)
            if match:
                resolved_by_name += 1
                log(f"  {pak_file} -> {match['archive']} (par nom)")
                continue

            if divine_exe is not None:
                pak_path = self._config.managed_mods_link / pak_file
                match = match_orphan_by_uuid(
                    pak_path,
                    archives,
                    archives_dir=self._config.archives_dir,
                    archives_installed_dir=self._config.archives_installed_dir,
                    archives_pending_dir=self._config.archives_pending_dir,
                    divine_exe=divine_exe,
                    reference_path=self._config.project_root,
                    log=log,
                )
                if match:
                    resolved_by_uuid += 1
                    log(f"  {pak_file} -> {match['archive']} (par UUID)")
                    continue

            unresolved.append(pak)

        log(
            f"{resolved_by_name} par nom, {resolved_by_uuid} par UUID, "
            f"{already_manual} déjà renseigné(s) manuellement, "
            f"{len(unresolved)} sans correspondance automatique."
        )

        if unresolved:
            self.app.call_from_thread(self._prompt_manual_pak_origins, unresolved)

    def _prompt_manual_pak_origins(self, paks: list[dict]) -> None:
        """Demande, l'un après l'autre (modal), un lien Nexus/mod.io pour
        chaque .pak de `paks` — étape 3 de `run_resolve_pak_origins`,
        appelée sur le thread UI (poussée d'écran modale)."""
        def prompt_next(index: int) -> None:
            if index >= len(paks):
                return
            pak_file = paks[index]["file"]

            def on_url(url: str | None) -> None:
                if url:
                    origin = save_manual_origin(
                        self._config.profiles_dir, self._config.active_profile, pak_file, url
                    )
                    if origin is None:
                        self._log(
                            f"[#C46F6F]{pak_file} : lien non reconnu (ni Nexus, ni "
                            f"mod.io) — ignoré.[/#C46F6F]"
                        )
                    else:
                        self._log(f"{pak_file} : origine enregistrée -> {origin.url}")
                prompt_next(index + 1)

            self.app.push_screen(ManualPakOriginPromptScreen(pak_file), on_url)

        prompt_next(0)

    @on(Button.Pressed, "#action-validate-paks")
    def handle_validate_paks(self) -> None:
        self.run_validate_paks()

    @work(exclusive=True, thread=True, exit_on_error=False)
    def run_validate_paks(self) -> None:
        """Sous-tâche 6c du TODO "Utilitaire standalone de validation .pak" :
        câble `pak_validator.validate_paks` sur tous les .pak actuellement
        déployés dans Mods/ — lecture seule au sens strict (voir
        `pak_validator`, docstring du module) : n'écrit rien d'autre que le
        rapport `pak_validation.md`, ne régénère pas modsettings.lsx et ne
        lance pas le jeu."""
        def log(msg): return self.app.call_from_thread(self._log, msg)
        log("=== Validation des .pak déployés (check structurel natif) ===")

        pak_paths = sorted(self._config.managed_mods_link.glob("*.pak"))
        if not pak_paths:
            log("Aucun .pak actuellement déployé dans Mods/.")
            return

        log(f"{len(pak_paths)} .pak à valider (échantillonnage sur les gros .pak, voir pak_validator)...")
        report = validate_paks(pak_paths)
        self._write_pak_validation_report(report)

    def _write_pak_validation_report(self, report: dict[str, list]) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)

        invalid = report["invalid"]
        valid = report["valid"]
        report_dir = profile_data_dir(self._config.profiles_dir, self._config.active_profile)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "pak_validation.md"

        lines = ["# Validation structurelle des .pak déployés\n"]
        lines.append(
            "Check natif (sans Divine.exe) : header LSPK + échantillon des entrées "
            "décompressées avec succès. **Ne remplace pas Divine.exe** (pas de "
            "génération de modsettings.lsx, pas de lancement du jeu) — voir "
            "`pak_validator.py` pour les limites détaillées.\n"
        )
        if invalid:
            lines.append(f"{len(invalid)} .pak invalide(s) sur {len(report['valid']) + len(invalid)} :\n")
            for result in sorted(invalid, key=lambda r: r.path.name):
                lines.append(f"## {result.path.name}\n")
                for error in result.errors:
                    lines.append(f"- {error}")
                lines.append("")
        else:
            lines.append(f"Les {len(valid)} .pak déployé(s) sont structurellement valides (échantillon vérifié).")

        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if invalid:
            log(f"[#C46F6F]{len(invalid)} .pak invalide(s)[/#C46F6F] sur {len(valid) + len(invalid)} -> {report_path}")
        else:
            log(f"{len(valid)} .pak valide(s) -> {report_path}")

    @on(Button.Pressed, "#action-nexus-updates")
    def handle_nexus_updates(self) -> None:
        # Lecture seule (archives locales + API Nexus), écrit son propre
        # rapport (nexus_updates.md).
        self._start_task(
            title="Vérifier les mises à jour Nexus...",
            resource_tags=frozenset(),
            launch=self.run_nexus_updates,
        )

    @work(exclusive=True, thread=True, group="run_nexus_updates", exit_on_error=False)
    def run_nexus_updates(self, log: Callable[[str], None]) -> None:
        """Sous-tâche 3 du TODO "Priorisation Nexus / Mod.io" : compare
        chaque archive Nexus connue localement à la version actuellement
        publiée sur Nexus (voir `mod_pipeline.check_nexus_updates`).
        Lecture seule — ne télécharge ni ne modifie rien, seulement un
        rapport (`nexus_updates.md`, même emplacement que
        `archives_orphelines.md`)."""
        log("=== Vérification des mises à jour Nexus ===")
        try:
            archives = scan_all_archives(
                archives_dir=self._config.archives_dir,
                archives_installed_dir=self._config.archives_installed_dir,
                archives_pending_dir=self._config.archives_pending_dir,
                on_progress=log,
            )
        except OSError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return

        known = [a for a in archives if a.nexus_mod_id is not None]
        if not known:
            log("Aucune archive Nexus reconnue localement (aucun ID Nexus retrouvé dans les noms de fichiers).")
            return

        try:
            client = NexusClient(os.environ.get("NEXUS_API_KEY", ""))
        except NexusAPIError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return

        report = check_nexus_updates(client, known, log=log)
        self._write_nexus_updates_report(report, log=log)

        # Sous-tâche 4d du TODO ("Câbler `check_nexus_updates` au
        # téléchargement") : dès que le rapport signale des mods obsolètes,
        # proposer immédiatement leur re-téléchargement en un clic plutôt
        # que de laisser `nexus_updates.md` comme une simple liste à
        # consulter à part, sans lien avec le téléchargement. Le wizard
        # (`NexusOutdatedModsScreen`, un `push_screen` Textual) doit
        # tourner sur le thread principal — `run_nexus_updates` tourne sur
        # un thread de worker (voir `@work(thread=True)` ci-dessus).
        if report["outdated"]:
            self.app.call_from_thread(self._prompt_redownload_outdated, report["outdated"])

    def _prompt_redownload_outdated(self, outdated: list[dict]) -> None:
        """Affiche `NexusOutdatedModsScreen` (liste des mods obsolètes,
        voir `run_nexus_updates`) et, si l'utilisateur en coche puis
        valide, lance leur re-téléchargement via `run_redownload_nexus_outdated`
        — même mécanisme de verrouillage de ressources
        (`resource_tags={"archives"}`) que "Télécharger les mods", pour ne
        pas écrire dans `archives_dir` en même temps qu'un téléchargement/
        nettoyage déjà en cours."""

        def on_result(chosen: list[int] | None) -> None:
            if not chosen:
                return
            self._start_task(
                title=f"Re-télécharger {len(chosen)} mod(s) Nexus obsolète(s)",
                resource_tags=frozenset({"archives"}),
                launch=lambda log: self.run_redownload_nexus_outdated(chosen, log),
            )

        self.app.push_screen(NexusOutdatedModsScreen(outdated), on_result)

    @work(exclusive=True, thread=True, group="run_redownload_nexus_outdated", exit_on_error=False)
    def run_redownload_nexus_outdated(self, mod_ids: list[int], log: Callable[[str], None]) -> None:
        """Re-télécharge, un par un, les mods choisis dans
        `NexusOutdatedModsScreen` — voir `mod_pipeline.redownload_nexus_mod`
        (même chemin que `run_download_mods`, `skip_existing=False` pour
        ne pas sauter un mod déjà présent en version périmée)."""
        log(f"=== Re-téléchargement de {len(mod_ids)} mod(s) Nexus obsolète(s) ===")
        try:
            client = NexusClient(os.environ.get("NEXUS_API_KEY", ""))
        except NexusAPIError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return

        downloaded = 0
        failed = 0
        for mod_id in mod_ids:
            try:
                report = redownload_nexus_mod(
                    client,
                    mod_id,
                    self._config.archives_dir,
                    archives_installed_dir=self._config.archives_installed_dir,
                    archives_pending_dir=self._config.archives_pending_dir,
                    profiles_dir=self._config.profiles_dir,
                    profile_name=self._config.active_profile,
                    select_files=self._select_nexus_files,
                    on_download_progress=self._on_download_progress,
                    log=log,
                )
            except NexusAPIError as exc:
                log(f"[#C46F6F]Erreur ({mod_id}) : {exc}[/#C46F6F]")
                failed += 1
                continue
            except Exception as exc:
                log(f"[#C46F6F]Erreur inattendue ({mod_id}) : {exc}[/#C46F6F]")
                failed += 1
                continue
            downloaded += len(report["downloaded"])
            failed += len(report["failed"])

        log(f"Terminé : {downloaded} mod(s) re-téléchargé(s), {failed} échec(s).")

    def _write_nexus_updates_report(
        self, report: dict[str, list], *, log: Callable[[str], None]
    ) -> None:
        outdated = report["outdated"]
        report_dir = profile_data_dir(self._config.profiles_dir, self._config.active_profile)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "nexus_updates.md"

        lines = ["# Mods Nexus obsolètes localement\n"]
        if outdated:
            lines.append(
                f"{len(outdated)} mod(s) dont la version disponible sur Nexus "
                f"est plus récente que l'archive connue localement — "
                f"{len(report['up_to_date'])} déjà à jour, "
                f"{len(report['failed'])} non vérifiable(s).\n"
            )
            lines += ["| Mod | Version locale | Version Nexus | Archive |", "|---|---|---|---|"]
            for entry in sorted(outdated, key=lambda e: e["mod_name_guess"] or e["archive"]):
                name = entry["mod_name_guess"] or entry["archive"]
                origin = f"[{name}]({entry['nexus_url']})" if entry.get("nexus_url") else name
                lines.append(
                    f"| {origin} | {entry['local_version'] or '?'} | "
                    f"{entry['remote_version']} | {entry['archive']} |"
                )
        else:
            lines.append(
                f"Toutes les archives Nexus connues localement ({len(report['up_to_date'])}) "
                f"sont à jour par rapport à Nexus."
            )
        if report["failed"]:
            lines.append(f"\n{len(report['failed'])} mod(s) non vérifiable(s) (erreur API, voir logs).")

        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log(f"{len(outdated)} mod(s) obsolète(s) -> {report_path}")

    @on(Button.Pressed, "#action-nexus-blacklist")
    def handle_nexus_blacklist(self) -> None:
        blacklist = load_blacklisted_files(self._config.profiles_dir, self._config.active_profile)
        if not blacklist:
            self._log("Aucun fichier Nexus écarté pour le profil actif.")
            return

        def on_result(chosen: list[tuple[int, int]] | None) -> None:
            if not chosen:
                return
            for mod_id, file_id in chosen:
                blacklist.get(mod_id, {}).pop(file_id, None)
            save_blacklisted_files(self._config.profiles_dir, self._config.active_profile, blacklist)
            self._log(
                f"{len(chosen)} fichier(s) Nexus retiré(s) de la blacklist — "
                "seront reproposés au prochain téléchargement."
            )

        self.app.push_screen(NexusBlacklistScreen(blacklist), on_result)

    def _reset_profile_select(self, to_value: str | None = None) -> None:
        """Recharge les options du sélecteur de profil et le repositionne
        sur `to_value` (ou le profil actif de la config, par défaut)."""
        select = self.query_one("#profile-select", Select)
        select.set_options(self._profile_select_options())
        target = to_value if to_value is not None else self._config.active_profile
        profiles = list_profiles(self._config.profiles_dir)
        select.value = target if target in profiles else Select.NULL

    # Ressources écrites par la restauration/l'import d'un profil : Mods/,
    # les mods DLL déployés et modsettings.lsx — la même exigence de
    # sérialisation que pour "Extraire vers Mods/" ou "Nettoyer les .pak".
    _PROFILE_WRITE_TAGS = frozenset({"mods-dir", "native-mods", "modsettings"})

    @on(Select.Changed, "#profile-select")
    def handle_profile_changed(self, event: Select.Changed) -> None:
        value = event.value
        if value is Select.NULL:
            return

        if value == NEW_PROFILE_OPTION:
            def on_name(name: str | None) -> None:
                if name:
                    self._start_task(
                        title=f"Sauvegarder profil « {name} »",
                        resource_tags=frozenset(),
                        launch=lambda log: self.run_save_profile(name, log),
                    )
                else:
                    self._reset_profile_select()

            self.app.push_screen(ProfileNamePromptScreen(), on_name)
            return

        if value == self._config.active_profile:
            # `Select` poste toujours un `Changed` quand sa valeur passe de
            # NULL à sa valeur initiale (montage de l'écran, ou
            # `_reset_profile_select`) — ce n'est pas un choix de
            # l'utilisateur. Le profil actif est déjà en place (fichiers
            # déjà déployés) : le restaurer à nouveau ici écraserait sans
            # raison un `modsettings.lsx` éventuellement modifié en jeu
            # depuis la dernière restauration.
            return

        name = str(value)
        self._start_task(
            title=f"Restaurer profil « {name} »",
            resource_tags=self._PROFILE_WRITE_TAGS,
            launch=lambda log: self.run_restore_profile(name, log),
        )

    @work(exclusive=True, thread=True, group="run_restore_profile", exit_on_error=False)
    def run_restore_profile(self, name: str, log: Callable[[str], None]) -> None:
        self._restore_profile_task(name, log)

    def _restore_profile_task(self, name: str, log: Callable[[str], None]) -> None:
        """Corps effectif de la restauration d'un profil — factorisé pour
        être appelé à la fois par `run_restore_profile` (worker dédié,
        déclenché par le sélecteur de profil) et directement par
        `run_import_profile` en fin d'import (même thread, même onglet de
        log : l'import d'un profil se termine toujours par sa
        restauration, ce n'est pas une tâche indépendante qui devrait
        passer par sa propre vérification de ressources/son propre
        onglet)."""
        log(f"=== Restauration du profil « {name} » ===")
        try:
            report = restore_profile(
                name,
                profiles_dir=self._config.profiles_dir,
                modsettings_path=self._config.appdata_modsettings_path,
                mods_dir=self._config.managed_mods_link,
                loose_mods_dir=self._config.loose_mods_managed_dir,
                game_data_dir=self._config.game_data_dir,
                native_mods_dir=self._config.native_mods_deployed_dir,
                previous_profile=self._config.active_profile,
                log=log,
            )
            self._config.active_profile = name
            save_config(self._config)

            if report.paks_missing:
                log(
                    f"[#D8C091]{len(report.paks_missing)} .pak du profil absent(s) de Mods/ : "
                    f"{', '.join(report.paks_missing)}[/#D8C091]"
                )
            if report.paks_extra:
                log(
                    f"[#D8C091]{len(report.paks_extra)} .pak présent(s) dans Mods/ mais absent(s) "
                    f"du profil : {', '.join(report.paks_extra)}[/#D8C091]"
                )
            if not report.paks_missing and not report.paks_extra:
                log("Les .pak de Mods/ correspondent exactement au profil.")
            if report.native_mods_missing:
                log(
                    f"[#D8C091]{len(report.native_mods_missing)} mod(s) DLL du profil absent(s) de "
                    f"bin/NativeMods/ : {', '.join(report.native_mods_missing)}[/#D8C091]"
                )
            if report.native_mods_extra:
                log(
                    f"[#D8C091]{len(report.native_mods_extra)} mod(s) DLL présent(s) dans "
                    f"bin/NativeMods/ mais absent(s) du profil : {', '.join(report.native_mods_extra)}[/#D8C091]"
                )
            log(f"Profil « {name} » restauré ({report.loose_files_linked} fichier(s) loose reliés).")
        except ProfileError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @work(exclusive=True, thread=True, group="run_save_profile", exit_on_error=False)
    def run_save_profile(self, name: str, log: Callable[[str], None]) -> None:
        log(f"=== Sauvegarde du profil « {name} » ===")
        try:
            archives = scan_all_archives(
                archives_dir=self._config.archives_dir,
                archives_installed_dir=self._config.archives_installed_dir,
                archives_pending_dir=self._config.archives_pending_dir,
            )
            dest = save_profile(
                name,
                profiles_dir=self._config.profiles_dir,
                modsettings_path=self._config.appdata_modsettings_path,
                mods_dir=self._config.managed_mods_link,
                loose_mods_dir=self._config.loose_mods_managed_dir,
                native_mods_dir=self._config.native_mods_deployed_dir,
                archives=archives,
            )
            log(f"Profil sauvegardé -> {dest}")
            self._config.active_profile = name
            save_config(self._config)
            self.app.call_from_thread(self._reset_profile_select, name)
        except ProfileError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            self.app.call_from_thread(self._reset_profile_select)

    @on(Button.Pressed, "#action-export-profile")
    def handle_export_profile(self) -> None:
        name = self._config.active_profile
        if not name:
            self._log("[#D8C091]Aucun profil actif à exporter.[/#D8C091]")
            return
        # Lecture seule (profil + Mods/), écrit une archive isolée sous
        # web_root_dir : peut tourner en parallèle de tout.
        self._start_task(
            title="Exporter le profil actif",
            resource_tags=frozenset(),
            launch=lambda log: self.run_export_profile(name, log),
        )

    @work(exclusive=True, thread=True, group="run_export_profile", exit_on_error=False)
    def run_export_profile(self, name: str, log: Callable[[str], None]) -> None:
        log(f"=== Export du profil « {name} » ===")
        try:
            # Publiée sous www-data (servie par le bouton "Web") plutôt que
            # dans le dossier du projet — nom déterministe (slug du profil,
            # sans horodatage) : un nouvel export du même profil remplace
            # l'ancien plutôt que de s'accumuler à côté.
            dest_path = self._config.web_root_dir / \
                f"{slugify_profile_name(name)}{ARCHIVE_SUFFIX}"
            export_profile_archive(
                name,
                profiles_dir=self._config.profiles_dir,
                mods_dir=self._config.managed_mods_link,
                loose_mods_dir=self._config.loose_mods_managed_dir,
                native_mods_dir=self._config.native_mods_deployed_dir,
                native_mods_manifest_path=self._config.native_mods_manifest_file,
                inventory_path=self._config.inventory_file,
                dest_path=dest_path,
                log=log,
            )
            log(f"Archive prête à être partagée : {dest_path}")
        except ProfileError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-import-profile")
    def handle_import_profile(self) -> None:
        def on_path(path_str: str | None) -> None:
            if path_str:
                archive_path = Path(path_str).expanduser()
                # Mêmes ressources que la restauration : l'import se
                # termine toujours par une restauration (voir
                # `run_import_profile`).
                self._start_task(
                    title="Importer un profil...",
                    resource_tags=self._PROFILE_WRITE_TAGS,
                    launch=lambda log: self.run_import_profile(archive_path, log),
                )

        self.app.push_screen(ImportArchivePromptScreen(), on_path)

    @work(exclusive=True, thread=True, group="run_import_profile", exit_on_error=False)
    def run_import_profile(self, archive_path: Path, log: Callable[[str], None]) -> None:
        log(f"=== Import du profil depuis {archive_path} ===")
        try:
            name = import_profile_archive(
                archive_path,
                profiles_dir=self._config.profiles_dir,
                mods_dir=self._config.managed_mods_link,
                loose_mods_dir=self._config.loose_mods_managed_dir,
                native_mods_dir=self._config.native_mods_deployed_dir,
                native_mods_manifest_path=self._config.native_mods_manifest_file,
                log=log,
            )
        except ProfileArchiveError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return

        self.app.call_from_thread(self._reset_profile_select, name)
        # Poursuite directe (même thread, même onglet de log, même
        # réservation de ressources) plutôt qu'un nouveau worker
        # `run_restore_profile` : voir le docstring de
        # `_restore_profile_task`.
        self._restore_profile_task(name, log)

    @on(Button.Pressed, "#action-optimize-prefix")
    def handle_optimize_prefix(self) -> None:
        # Sous-tâche 7d : même routage "Outils" que `handle_launch_tool` —
        # profite aussi de `group=` explicite ci-dessous (absent avant ce
        # correctif, ce qui partageait le groupe "default" de `@work` avec
        # `run_validate_paks` et pouvait annuler l'un des deux workers).
        self._start_task(
            title="Optimiser le préfixe",
            resource_tags=frozenset(),
            launch=self.run_optimize_prefix,
            pool="tools",
        )

    @work(exclusive=True, thread=True, group="run_optimize_prefix", exit_on_error=False)
    def run_optimize_prefix(self, log: Callable[[str], None]) -> None:
        log("=== Optimisation du préfixe Proton pour les outils ===")
        try:
            prefix = find_proton_prefix(self._config.appdata_path)
            if prefix is None:
                log("[#C46F6F]Impossible de déterminer le préfixe Proton de BG3.[/#C46F6F]")
                return
            wine_bin = resolve_wine_bin(prefix)
            appid = prefix.parent.name
            tool_executables = find_executables(self._config.tools_dir)
            optimize_prefix_for_tools(
                appid=appid,
                wine_bin=wine_bin,
                prefix=prefix,
                tool_executables=tool_executables,
                log_dir=self._config.logs_dir,
                log=log,
            )
            log("Terminé.")
        except (LauncherError, WinePrefixError) as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-quit")
    def handle_quit(self) -> None:
        self._stop_web_server_if_running()
        self.app.exit()

    def action_quit_app(self) -> None:
        self._stop_web_server_if_running()
        self.app.exit()

    def _stop_web_server_if_running(self) -> None:
        if self._web_server_handle is not None:
            self._web_server_handle.stop()
            self._web_server_handle = None

    def _web_log(self, message: str) -> None:
        # Pas de `_mark_log_tab_active` ici : Web n'est plus dans un onglet
        # (toujours visible en bleu à droite — sous-tâche 7c/7d), donc plus
        # besoin d'indicateur "●" pour signaler un message reçu en arrière-plan.
        try:
            self.query_one("#web-console-log", ConsoleLog).write(message)
        except Exception:
            pass

    @on(Button.Pressed, "#planet-button")
    def handle_planet_button(self) -> None:
        if self._web_server_handle is not None and self._web_server_handle.is_running:
            self._stop_web_server()
            return

        if not self._config.has_public_address():

            def on_address(result: tuple[str, str] | None) -> None:
                if result is None:
                    return
                url, port = result
                self._config.public_url = url
                self._config.public_port = port
                save_config(self._config)
                self._start_web_server()

            self.app.push_screen(PublicAddressPromptScreen(), on_address)
            return

        self._start_web_server()

    def _start_web_server(self) -> None:
        button = self.query_one("#planet-button", Button)
        web_root = self._config.web_root_dir
        web_root.mkdir(parents=True, exist_ok=True)
        try:
            handle = start_http_server(
                web_root,
                self._config.public_port,
                on_line=lambda line: self.app.call_from_thread(
                    self._web_log, fmt_http_log_line(line)),
            )
        except (ValueError, OSError) as exc:
            self._web_log(f"[#C46F6F]Échec du démarrage du serveur : {exc}[/#C46F6F]")
            return

        self._web_server_handle = handle
        button.variant = "success"
        self.query_one("#action-class-builder", Button).disabled = False

        link = self._web_base_url()
        self._web_log(link)
        self._web_log(f"Racine servie : {web_root}")

    def _web_base_url(self) -> str:
        """URL de base du serveur Web actuellement démarré (adresse publique
        déclarée si renseignée, sinon boucle locale) — factorisé pour être
        réutilisé par `_start_web_server` (message de log) et
        `handle_class_builder` (page servie plutôt qu'ouverte en `file://`)."""
        if self._config.public_url:
            return f"{self._config.public_url.rstrip('/')}:{self._config.public_port}/"
        return f"http://127.0.0.1:{self._config.public_port}/"

    def _stop_web_server(self) -> None:
        self._web_log("Arrêt du serveur...")
        self._stop_web_server_if_running()

        button = self.query_one("#planet-button", Button)
        button.variant = "warning" if not self._config.has_public_address() else "error"
        self.query_one("#action-class-builder", Button).disabled = True
