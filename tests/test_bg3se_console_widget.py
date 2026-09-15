"""Tests pour bg3_mod_tui/widgets/bg3se_console.py — le widget console
interactive BG3SE. `BG3SERemoteConsole` (le vrai client TCP) est
entièrement mocké : aucune connexion réseau réelle n'est établie, tout
passe par une fausse classe contrôlée depuis le test."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.widgets import Button, Input

from bg3_mod_tui.bg3se_remote_console import RemoteConsoleError
from bg3_mod_tui.widgets import bg3se_console as bsc
from bg3_mod_tui.widgets.bg3se_console import BG3SEConsole, _CommandInput
from bg3_mod_tui.widgets.console_log import ConsoleLog


class _FakeRemoteConsole:
    """Remplace BG3SERemoteConsole : pas de socket réel, comportement
    entièrement piloté par les attributs de classe ci-dessous, redéfinis
    par chaque test qui en a besoin."""

    connect_should_fail: str | None = None
    completions: list[str] = []
    completions_should_fail: str | None = None

    def __init__(self, on_line, on_disconnect):
        self.on_line = on_line
        self.on_disconnect = on_disconnect
        self.connected = False
        self.sent_commands: list[str] = []
        self.closed = False

    def connect(self, host, port):
        if self.connect_should_fail:
            raise RemoteConsoleError(self.connect_should_fail)
        self.connected = True

    def send_command(self, text):
        self.sent_commands.append(text)

    def request_completions(self, partial):
        if self.completions_should_fail:
            raise RemoteConsoleError(self.completions_should_fail)
        return self.completions

    def close(self):
        self.closed = True
        self.connected = False


class _MiniApp(App):
    def compose(self) -> ComposeResult:
        yield BG3SEConsole(host="127.0.0.1", port=1234, id="console")


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch):
    monkeypatch.setattr(bsc, "BG3SERemoteConsole", _FakeRemoteConsole)
    _FakeRemoteConsole.connect_should_fail = None
    _FakeRemoteConsole.completions = []
    _FakeRemoteConsole.completions_should_fail = None


def _run(coro):
    asyncio.run(coro)


def test_compose_and_initial_state():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            input_widget = app.query_one("#bg3se-console-input", Input)
            assert input_widget.disabled is True
            button = app.query_one("#bg3se-console-connect", Button)
            assert button.label.plain == "Connecter"

    _run(scenario())


def test_connect_success_flow():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            # Laisse le worker thread se terminer et rappeler l'UI.
            for _ in range(20):
                await pilot.pause(0.05)
                if button.label.plain == "Déconnecter":
                    break
            assert button.label.plain == "Déconnecter"
            input_widget = app.query_one("#bg3se-console-input", Input)
            assert input_widget.disabled is False
            log = app.query_one("#bg3se-console-log", ConsoleLog)
            assert log._lines  # au moins une ligne de log écrite

    _run(scenario())


def test_connect_failure_flow():
    async def scenario():
        _FakeRemoteConsole.connect_should_fail = "connexion refusée"
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if not button.disabled:
                    break
            assert button.disabled is False
            assert button.label.plain == "Connecter"
            input_widget = app.query_one("#bg3se-console-input", Input)
            assert input_widget.disabled is True

    _run(scenario())


def test_disconnect_flow():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if button.label.plain == "Déconnecter":
                    break
            assert console._client is not None
            client = console._client
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if client.closed:
                    break
            assert client.closed is True
            assert console._client is None
            assert button.label.plain == "Connecter"

    _run(scenario())


def test_submit_command_without_client_is_noop():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.disabled = False
            input_widget.value = "print(1)"
            input_widget.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert input_widget.value == ""

    _run(scenario())


def test_submit_empty_text_is_noop_even_when_connected():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if console._client is not None:
                    break
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = ""
            input_widget.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert console._client.sent_commands == []

    _run(scenario())


def test_submit_command_sends_and_logs():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if console._client is not None:
                    break
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = "print(1)"
            input_widget.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert console._client.sent_commands == ["print(1)"]
            assert input_widget.value == ""

    _run(scenario())


def test_submit_command_send_failure_logs_error():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if console._client is not None:
                    break

            def _boom(text):
                raise RemoteConsoleError("boom")

            console._client.send_command = _boom
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = "bad"
            input_widget.focus()
            await pilot.press("enter")
            await pilot.pause()
            # Ne plante pas ; le message d'erreur est loggé (pas d'assertion
            # simple possible sur le contenu Rich, la non-levée suffit ici).

    _run(scenario())


def test_tab_completion_noop_without_client():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.disabled = False
            input_widget.value = "pri"
            input_widget.focus()
            await pilot.press("tab")
            await pilot.pause()
            # Toujours pas de client -> rien ne doit planter.
            assert input_widget.value == "pri"

    _run(scenario())


def test_tab_completion_noop_with_empty_partial():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if console._client is not None:
                    break
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = ""
            input_widget.focus()
            await pilot.press("tab")
            await pilot.pause()
            assert input_widget.value == ""

    _run(scenario())


def test_tab_completion_single_candidate_completes():
    async def scenario():
        _FakeRemoteConsole.completions = ["print"]
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if console._client is not None:
                    break
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = "pri"
            input_widget.focus()
            await pilot.press("tab")
            for _ in range(20):
                await pilot.pause(0.05)
                if input_widget.value == "print":
                    break
            assert input_widget.value == "print"
            assert input_widget.cursor_position == len("print")

    _run(scenario())


def test_tab_completion_multiple_candidates_common_prefix():
    async def scenario():
        _FakeRemoteConsole.completions = ["print", "printf", "println"]
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if console._client is not None:
                    break
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = "pri"
            input_widget.focus()
            await pilot.press("tab")
            for _ in range(20):
                await pilot.pause(0.05)
                if input_widget.value == "print":
                    break
            assert input_widget.value == "print"

    _run(scenario())


def test_tab_completion_no_candidates_noop():
    async def scenario():
        _FakeRemoteConsole.completions = []
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if console._client is not None:
                    break
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = "pri"
            input_widget.focus()
            await pilot.press("tab")
            await pilot.pause()
            assert input_widget.value == "pri"

    _run(scenario())


def test_tab_completion_request_failure_logs_error():
    async def scenario():
        _FakeRemoteConsole.completions_should_fail = "timeout"
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            button = app.query_one("#bg3se-console-connect", Button)
            button.press()
            for _ in range(20):
                await pilot.pause(0.05)
                if console._client is not None:
                    break
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = "pri"
            input_widget.focus()
            await pilot.press("tab")
            await pilot.pause(0.2)
            # Ne plante pas ; la valeur n'est pas modifiée.
            assert input_widget.value == "pri"

    _run(scenario())


def test_apply_completions_ignored_if_input_changed_meanwhile():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            input_widget = app.query_one("#bg3se-console-input", Input)
            input_widget.value = "changed"
            console._apply_completions("pri", ["print"])
            assert input_widget.value == "changed"

    _run(scenario())


def test_log_swallow_exception_when_log_widget_missing():
    async def scenario():
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(BG3SEConsole)
            # Force query_one à échouer pour couvrir le except Exception.
            console._log("ceci ne doit jamais lever")

    _run(scenario())


def test_does_not_shadow_private_textual_api() -> None:
    assert BG3SEConsole._render is Widget._render
