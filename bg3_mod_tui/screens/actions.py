"""Écran principal : menu d'actions (téléchargement, nettoyage, extraction,
outils) plutôt qu'une liste de mods à parcourir."""

from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Select, SelectionList

from bg3_mod_tui.compat_framework import (
    CompatibilityFrameworkError,
    build_pak as build_compat_framework_pak,
    find_divine_exe,
)
from bg3_mod_tui.config import ModToolsConfig, save_config
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
from bg3_mod_tui.native_mods import (
    NativeModsManifestError,
    deploy_native_mods_from_manifest,
    load_manifest as load_native_mods_manifest,
)
from bg3_mod_tui.pak_metadata import archive_pak_identities, build_deployed_uuid_index
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
    restore_profile,
    save_blacklisted_files,
    save_profile,
    slugify_profile_name,
)
from bg3_mod_tui.webserver import WebServerHandle, start_http_server
from bg3_mod_tui.wineprefix import WinePrefixError, optimize_prefix_for_tools
from bg3_mod_tui.mod_pipeline import (
    clean_pak_files,
    download_mods_from_links_file,
    download_subscribed_modio_mods,
    extract_archives_to_mods,
)
from bg3_mod_tui.providers.modio import ModIOAPIError, ModIOClient
from bg3_mod_tui.providers.nexus import NexusAPIError, NexusClient
from bg3_mod_tui.tools_manager import ToolsError, download_and_extract_tool, find_executables, parse_tools_table
from bg3_mod_tui.widgets.console_log import ConsoleLog


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


NEW_PROFILE_OPTION = "__new_profile__"


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
    #logs-panel {
        margin-left: 2;
        width: 1fr;
    }
    #actions-log-label {
        height: auto;
    }
    #actions-log {
        border: round $panel;
        height: 1fr;
    }
    #tools-log-label {
        margin-top: 1;
        height: auto;
    }
    #tools-log {
        border: round $accent;
        height: 10;
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
    /* Bouton "internet" : un bouton normal comme les autres (couleur selon
       l'état via la variante warning/error/success standard de Button) —
       icône et image abandonnées (peu lisibles/non fiables selon le
       terminal), on garde juste le code couleur. */
    #planet-button {
        margin-left: 2;
        width: 14;
    }
    #web-console-panel {
        width: 30;
        height: 1fr;
        margin-left: 2;
    }
    #web-console-label {
        height: auto;
        text-style: bold;
        color: $text-accent;
    }
    #web-console-log {
        border: round $accent;
        height: 1fr;
    }
    """

    BINDINGS = [("q", "quit_app", "Quitter")]

    def __init__(self, config: ModToolsConfig) -> None:
        super().__init__()
        self._config = config
        self._web_server_handle = None

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
                        "MAJ des outils",
                        id="action-tools",
                        tooltip="Télécharge ou met à jour les outils listés dans Tools/TOOLS.md (BG3 Mod Manager, Load Order Optimizer, Script Extender, ExportTools/LSLib, Para Tool...).",
                    )
                    yield Button(
                        "Compiler Compat. Framework",
                        id="action-compat-framework",
                        tooltip=(
                            "BG3 Compatibility Framework n'a ni release GitHub avec .pak "
                            "tout fait, ni .pak commité dans son dépôt (juste les "
                            "sources) : ce bouton l'empaquette en .pak via Divine.exe "
                            "(LSLib) et le dépose dans Mods/ — nécessite d'avoir "
                            "téléchargé l'outil (MAJ des outils) au préalable."
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
                            "archives_orphelines.md, rien n'est supprimé "
                            "automatiquement."
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
            with Vertical(id="logs-panel"):
                yield Label("Console tâches", id="actions-log-label")
                yield ConsoleLog(id="actions-log", wrap=True, highlight=True, markup=True)
                yield Label("Console outils", id="tools-log-label")
                yield ConsoleLog(id="tools-log", wrap=True, highlight=True, markup=True)
            with Vertical(id="web-console-panel"):
                yield Label("Console Web", id="web-console-label")
                yield ConsoleLog(id="web-console-log", wrap=True, highlight=True, markup=True)
        yield Footer()

    def _log(self, message: str) -> None:
        self.query_one("#actions-log", ConsoleLog).write(message)

    def _tool_log(self, message: str) -> None:
        self.query_one("#tools-log", ConsoleLog).write(message)

    @on(Button.Pressed, "#action-download-mods")
    def handle_download_mods(self) -> None:
        self.run_download_mods()

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

    @work(exclusive=True, thread=True)
    def run_download_mods(self) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)

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
                client, self._config.archives_dir, log=log)
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
        self.run_clean_paks()

    @work(exclusive=True, thread=True)
    def run_clean_paks(self) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
        log("=== Nettoyage des .pak de Mods/ ===")
        clean_pak_files(
            self._config.managed_mods_link,
            native_mods_managed_dir=self._config.native_mods_managed_dir,
            log=log,
        )

    @on(Button.Pressed, "#action-sync-modsettings")
    def handle_sync_modsettings(self) -> None:
        self.run_sync_modsettings()

    @work(exclusive=True, thread=True)
    def run_sync_modsettings(self) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
        log("=== Synchronisation de modsettings.lsx ===")
        try:
            report = setup_links(self._config)
            for step in report.steps:
                log(step)
        except LinkingError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-extract")
    def handle_extract(self) -> None:
        self.run_extract()

    @work(exclusive=True, thread=True)
    def run_extract(self) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
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
            log=log,
        )
        log(
            f"Terminé : {len(report['installed'])} installée(s), "
            f"{len(report['pending'])} à traiter manuellement, "
            f"{len(report['failed'])} échec(s)."
        )

    @on(Button.Pressed, "#action-native-mods")
    def handle_native_mods(self) -> None:
        self.run_native_mods()

    @work(exclusive=True, thread=True)
    def run_native_mods(self) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
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

    @on(Button.Pressed, "#action-tools")
    def handle_tools(self) -> None:
        self.run_download_tools()

    @work(exclusive=True, thread=True)
    def run_download_tools(self) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
        log("=== Téléchargement/mise à jour des outils (TOOLS.md) ===")
        try:
            entries = parse_tools_table(self._config.tools_md_file)
        except ToolsError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")
            return
        for entry in entries:
            download_and_extract_tool(
                entry, self._config.project_root, log=log)

        log("--- Déploiement des DLL dans le jeu (bin/) ---")
        deploy_native_mod_loader(
            self._config.tools_dir, self._config.game_bin_dir, log=log)
        deploy_script_extender(self._config.tools_dir,
                               self._config.game_bin_dir, log=log)
        log("Terminé.")

    @on(Button.Pressed, "#action-compat-framework")
    def handle_compat_framework(self) -> None:
        self.run_build_compat_framework()

    @work(exclusive=True, thread=True)
    def run_build_compat_framework(self) -> None:
        log = lambda msg: self.app.call_from_thread(self._log, msg)
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
            self.run_launch_tool(exe_path)

        self.app.push_screen(ToolPickerScreen(
            executables, self._config.project_root), on_picked)

    @work(exclusive=False, thread=True)
    def run_launch_tool(self, exe_path: Path) -> None:
        def log(msg): return self.app.call_from_thread(self._tool_log, msg)
        log_dir = self._config.logs_dir
        try:
            launch_tool(
                exe_path, reference_path=self._config.appdata_path, log_dir=log_dir)
            log(f"Lancé : {exe_path.name} (sortie journalisée dans {log_dir / (exe_path.stem + '.log')})")
        except LauncherError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-protontricks")
    def handle_protontricks(self) -> None:
        self.run_protontricks()

    @work(exclusive=False, thread=True)
    def run_protontricks(self) -> None:
        def log(msg): return self.app.call_from_thread(self._tool_log, msg)
        log_dir = self._config.logs_dir
        try:
            open_protontricks(self._config.appdata_path, log_dir=log_dir)
            log(
                f"protontricks ouvert (préfixe BG3, sortie journalisée dans {log_dir / 'protontricks.log'}).")
        except LauncherError as exc:
            log(f"[#C46F6F]Erreur : {exc}[/#C46F6F]")

    @on(Button.Pressed, "#action-inventory")
    def handle_inventory(self) -> None:
        self.run_inventory()

    @work(exclusive=True, thread=True)
    def run_inventory(self) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
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
        self.run_orphaned_archives()

    @work(exclusive=True, thread=True)
    def run_orphaned_archives(self) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
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
            self._write_orphans_report(candidates, verified=False)
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

        confirmed: list[dict] = []
        unverifiable: list[dict] = []
        for index, archive in enumerate(candidates, start=1):
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
            elif not any(uuid in deployed_uuids for uuid, _name in identities):
                confirmed.append(archive)
            if index % 10 == 0 or index == len(candidates):
                log(f"  {index}/{len(candidates)} archive(s) vérifiée(s)...")

        discarded = len(candidates) - len(confirmed) - len(unverifiable)
        log(
            f"Vérification terminée : {len(confirmed)} orpheline(s) confirmée(s), "
            f"{discarded} faux positif(s) écarté(s) (mod toujours déployé, même "
            f"nom de fichier différent), {len(unverifiable)} non vérifiable(s) "
            f"(pas de .pak dedans)."
        )
        self._write_orphans_report(confirmed, verified=True, unverifiable=unverifiable)

    def _write_orphans_report(
        self,
        orphans: list[dict],
        *,
        verified: bool,
        unverifiable: list[dict] | None = None,
    ) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)

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

        report_path = self._config.project_root / "archives_orphelines.md"
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        log(
            f"{len(orphans)} archive(s) orpheline(s)"
            f"{' confirmée(s) par UUID' if verified else ''} "
            f"({_human_size(total_bytes)}) -> {report_path}"
        )

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

    @on(Select.Changed, "#profile-select")
    def handle_profile_changed(self, event: Select.Changed) -> None:
        value = event.value
        if value is Select.NULL:
            return

        if value == NEW_PROFILE_OPTION:
            def on_name(name: str | None) -> None:
                if name:
                    self.run_save_profile(name)
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

        self.run_restore_profile(str(value))

    @work(exclusive=True, thread=True)
    def run_restore_profile(self, name: str) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
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

    @work(exclusive=True, thread=True)
    def run_save_profile(self, name: str) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
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
        self.run_export_profile(name)

    @work(exclusive=True, thread=True)
    def run_export_profile(self, name: str) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
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
                self.run_import_profile(Path(path_str).expanduser())

        self.app.push_screen(ImportArchivePromptScreen(), on_path)

    @work(exclusive=True, thread=True)
    def run_import_profile(self, archive_path: Path) -> None:
        def log(msg): return self.app.call_from_thread(self._log, msg)
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
        self.app.call_from_thread(self.run_restore_profile, name)

    @on(Button.Pressed, "#action-optimize-prefix")
    def handle_optimize_prefix(self) -> None:
        self.run_optimize_prefix()

    @work(exclusive=True, thread=True)
    def run_optimize_prefix(self) -> None:
        def log(msg): return self.app.call_from_thread(self._tool_log, msg)
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

        if self._config.public_url:
            link = f"{self._config.public_url.rstrip('/')}:{self._config.public_port}/"
        else:
            link = f"http://127.0.0.1:{self._config.public_port}/"
        self._web_log(link)
        self._web_log(f"Racine servie : {web_root}")

    def _stop_web_server(self) -> None:
        self._web_log("Arrêt du serveur...")
        self._stop_web_server_if_running()

        button = self.query_one("#planet-button", Button)
        button.variant = "warning" if not self._config.has_public_address() else "error"
