"""Widget de console interactive BG3SE (section 11 du TODO) : un REPL Lua
bidirectionnel via le pont TCP `RemoteConsole` ajouté côté C++ (voir
`bg3_mod_tui/bg3se_remote_console.py` pour le client et le protocole, et
`Tools/BG3 Script Extender/BG3Extender/Extender/Shared/RemoteConsole.{h,cpp}`
côté serveur), plutôt que la console Win32 native (laggy sous le rendu GUI de
Wine/Proton).

S'intègre dans `ActionsScreen` comme un onglet supplémentaire du
`TabbedContent` "Outils" (`#tools-tabs`), au même titre que "Outils" — une
console persistante et interactive, pas un journal de tâche ponctuelle, donc
elle n'utilise PAS le mécanisme d'onglets dynamiques par tâche simultanée de
`_acquire_task_console` (section 7 du TODO) : un seul onglet fixe, comme
"Outils" et "Tâches" avant l'ajout de ce mécanisme.

NON TESTÉ contre un vrai process de jeu (voir `.claude/TODO.md` section 11) :
le patch C++ RemoteConsole n'a pas pu être buildé (pas de toolchain
Windows/MSVC disponible dans l'environnement où ce client a été écrit)."""

from __future__ import annotations

from textual import on, work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Input

from bg3_mod_tui.bg3se_remote_console import BG3SERemoteConsole, RemoteConsoleError
from bg3_mod_tui.widgets.console_log import ConsoleLog


class _CommandInput(Input):
    """`Input` standard, sauf pour la touche Tab : liée (BINDINGS, pas de
    méthode privée Textual redéfinie — voir
    `tests/test_no_private_textual_api_shadowing.py`, TODO 23b/25) à une
    demande de complétion au lieu du comportement par défaut (déplacement du
    focus, hérité des bindings globaux de `App`). Une `Binding` au niveau du
    widget qui a le focus est prioritaire sur celle, plus générale, de
    `App` — pas besoin d'intercepter la touche plus bas dans la pile
    d'événements."""

    BINDINGS = [Binding("tab", "request_complete", "Complétion", show=False)]

    class TabPressed(Message):
        """Posté quand la complétion est demandée (voir `BINDINGS`
        ci-dessus) — laisse `BG3SEConsole` décider quoi en faire. Porte le
        widget `Input` d'origine (`control`), comme les messages natifs de
        `Input` (`Input.Submitted`, etc.), pour que le décorateur
        `@on(..., "#bg3se-console-input")` puisse filtrer par sélecteur CSS
        dessus."""

        def __init__(self, input_widget: "_CommandInput") -> None:
            super().__init__()
            self.input = input_widget

        @property
        def control(self) -> "_CommandInput":
            return self.input

    def action_request_complete(self) -> None:
        self.post_message(self.TabPressed(self))


class BG3SEConsole(Vertical):
    """Console interactive BG3SE : zone de sortie en lecture seule
    (`ConsoleLog`), champ de saisie de commande avec complétion (Tab), et
    connexion/déconnexion au pont TCP `RemoteConsole` côté jeu."""

    DEFAULT_CSS = """
    BG3SEConsole {
        height: 1fr;
    }
    BG3SEConsole > #bg3se-console-log {
        height: 1fr;
    }
    BG3SEConsole > #bg3se-console-input-row {
        height: 3;
        align: left middle;
    }
    BG3SEConsole > #bg3se-console-input-row > Input {
        width: 1fr;
    }
    BG3SEConsole > #bg3se-console-input-row > Button {
        width: auto;
        margin-left: 1;
    }
    """

    def __init__(self, *, host: str, port: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self._host = host
        self._port = port
        self._client: BG3SERemoteConsole | None = None

    def compose(self):
        yield ConsoleLog(id="bg3se-console-log", wrap=True, highlight=True, markup=True)
        with Horizontal(id="bg3se-console-input-row"):
            yield _CommandInput(
                placeholder="Commande Lua ou spéciale (help, server, client, reset, silence on/off, clear, exit)…",
                id="bg3se-console-input",
                disabled=True,
            )
            yield Button("Connecter", id="bg3se-console-connect", variant="success")

    # -- Connexion --------------------------------------------------------

    @on(Button.Pressed, "#bg3se-console-connect")
    def _handle_connect_button(self, event: Button.Pressed) -> None:
        event.stop()
        if self._client is not None and self._client.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        button = self.query_one("#bg3se-console-connect", Button)
        button.disabled = True
        self._log(f"[cyan]Connexion à {self._host}:{self._port}…[/cyan]")
        self._connect_worker()

    @work(thread=True, exclusive=True, group="bg3se-console-connect")
    def _connect_worker(self) -> None:
        client = BG3SERemoteConsole(
            on_line=lambda line: self.app.call_from_thread(self._log, line),
            on_disconnect=lambda: self.app.call_from_thread(self._handle_disconnected),
        )
        try:
            client.connect(self._host, self._port)
        except RemoteConsoleError as exc:
            self.app.call_from_thread(self._handle_connect_failed, str(exc))
            return

        self._client = client
        self.app.call_from_thread(self._handle_connected)

    def _handle_connected(self) -> None:
        self._log("[green]Connecté à la console BG3SE.[/green]")
        self.query_one("#bg3se-console-input", Input).disabled = False
        button = self.query_one("#bg3se-console-connect", Button)
        button.label = "Déconnecter"
        button.variant = "error"
        button.disabled = False

    def _handle_connect_failed(self, message: str) -> None:
        self._log(f"[#C46F6F]{message}[/#C46F6F]")
        button = self.query_one("#bg3se-console-connect", Button)
        button.disabled = False

    def _handle_disconnected(self) -> None:
        self._client = None
        self._log("[#C46F6F]Déconnecté de la console BG3SE.[/#C46F6F]")
        self.query_one("#bg3se-console-input", Input).disabled = True
        button = self.query_one("#bg3se-console-connect", Button)
        button.label = "Connecter"
        button.variant = "success"
        button.disabled = False

    def _disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
        # _handle_disconnected() est aussi appelé par on_disconnect (thread de
        # lecture) : idempotent (query_one sur des attributs déjà à leur état
        # cible ne pose pas de souci), donc pas besoin de se coordonner ici.
        self._handle_disconnected()

    # -- Saisie de commande -------------------------------------------------

    @on(Input.Submitted, "#bg3se-console-input")
    def _handle_submit(self, event: Input.Submitted) -> None:
        event.stop()
        text = event.value
        input_widget = event.input
        input_widget.value = ""

        if not text or self._client is None or not self._client.connected:
            return

        self._log(f"[bold]>>[/bold] {text}")
        try:
            self._client.send_command(text)
        except RemoteConsoleError as exc:
            self._log(f"[#C46F6F]{exc}[/#C46F6F]")

    @on(_CommandInput.TabPressed, "#bg3se-console-input")
    def _handle_tab(self, event: _CommandInput.TabPressed) -> None:
        event.stop()
        input_widget = self.query_one("#bg3se-console-input", _CommandInput)
        partial = input_widget.value
        if not partial or self._client is None or not self._client.connected:
            return
        self._complete_worker(partial)

    @work(thread=True, exclusive=True, group="bg3se-console-complete")
    def _complete_worker(self, partial: str) -> None:
        client = self._client
        if client is None:
            return
        try:
            candidates = client.request_completions(partial)
        except RemoteConsoleError as exc:
            self.app.call_from_thread(self._log, f"[#C46F6F]{exc}[/#C46F6F]")
            return
        self.app.call_from_thread(self._apply_completions, partial, candidates)

    def _apply_completions(self, partial: str, candidates: list[str]) -> None:
        if not candidates:
            return

        input_widget = self.query_one("#bg3se-console-input", Input)
        # La saisie a pu changer pendant l'aller-retour réseau — n'applique la
        # complétion que si le préfixe demandé correspond toujours à ce qui
        # est affiché, pour éviter d'écraser une frappe plus récente.
        if input_widget.value != partial:
            return

        if len(candidates) == 1:
            input_widget.value = candidates[0]
            input_widget.cursor_position = len(candidates[0])
            return

        # Préfixe commun le plus long parmi les candidats, comme la
        # complétion de shell classique (bash/zsh) : complète jusqu'à
        # l'ambiguïté puis liste les possibilités sans deviner plus loin.
        common = candidates[0]
        for candidate in candidates[1:]:
            while not candidate.startswith(common):
                common = common[:-1]
                if not common:
                    break
        if len(common) > len(partial):
            input_widget.value = common
            input_widget.cursor_position = len(common)

        self._log("  " + "   ".join(candidates))

    # -- Sortie console -------------------------------------------------

    def _log(self, message: str) -> None:
        try:
            self.query_one("#bg3se-console-log", ConsoleLog).write(message)
        except Exception:
            return
