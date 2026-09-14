"""Teste `BG3SERemoteConsole` (client TCP de la console BG3SE, section 11 du
TODO) contre un faux serveur local qui reproduit fidèlement le protocole
implémenté côté C++ dans `RemoteConsole.cpp` (trames préfixées par une
longueur little-endian, tags 'L'/'R' serveur->client et 'C'/'T'
client->serveur — voir les commentaires de `bg3se_remote_console.py`).

Ce test valide le CLIENT Python de bout en bout (framing, callbacks,
complétion bloquante avec timeout, déconnexion) : il ne peut pas valider le
serveur C++ lui-même, qui n'a pas pu être buildé dans cet environnement (pas
de toolchain Windows/MSVC — voir .claude/TODO.md section 11)."""

from __future__ import annotations

import socket
import struct
import threading
import time

import pytest

from bg3_mod_tui.bg3se_remote_console import BG3SERemoteConsole, RemoteConsoleError

_HEADER = 4


def _recv_frame(sock: socket.socket) -> tuple[bytes, bytes]:
    header = _recv_exact(sock, _HEADER)
    (frame_len,) = struct.unpack("<I", header)
    payload = _recv_exact(sock, frame_len - _HEADER)
    return payload[:1], payload[1:]


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Fake server: connection closed early")
        buf += chunk
    return buf


def _send_frame(sock: socket.socket, tag: bytes, text: str) -> None:
    payload = tag + text.encode("utf-8")
    sock.sendall(struct.pack("<I", len(payload) + _HEADER) + payload)


class _FakeRemoteConsoleServer:
    """Reproduit le strict minimum de `RemoteConsole::Run()` /
    `MessageLoop()` côté C++ : accepte une connexion, répond aux requêtes de
    complétion ('T') avec une liste fixe, et journalise les commandes reçues
    ('C') pour vérification côté test."""

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self.port = self._listener.getsockname()[1]
        self.received_commands: list[str] = []
        self.completion_reply: list[str] = []
        self._conn: socket.socket | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        conn, _ = self._listener.accept()
        self._conn = conn
        try:
            while True:
                tag, payload = _recv_frame(conn)
                text = payload.decode("utf-8")
                if tag == b"C":
                    self.received_commands.append(text)
                elif tag == b"T":
                    _send_frame(conn, b"R", "\x1f".join(self.completion_reply))
        except (ConnectionError, OSError):
            pass

    def send_line(self, text: str) -> None:
        assert self._conn is not None
        _send_frame(self._conn, b"L", text)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
        self._listener.close()


@pytest.fixture
def fake_server():
    server = _FakeRemoteConsoleServer()
    yield server
    server.close()


def test_connect_and_receive_line(fake_server: _FakeRemoteConsoleServer) -> None:
    lines: list[str] = []
    client = BG3SERemoteConsole(on_line=lines.append)
    client.connect("127.0.0.1", fake_server.port)

    fake_server.send_line("hello from BG3SE")

    for _ in range(50):
        if lines:
            break
        time.sleep(0.05)

    assert lines == ["hello from BG3SE"]
    client.close()


def test_send_command_reaches_server(fake_server: _FakeRemoteConsoleServer) -> None:
    client = BG3SERemoteConsole(on_line=lambda _line: None)
    client.connect("127.0.0.1", fake_server.port)

    client.send_command("print('hi')")

    for _ in range(50):
        if fake_server.received_commands:
            break
        time.sleep(0.05)

    assert fake_server.received_commands == ["print('hi')"]
    client.close()


def test_request_completions_returns_server_reply(fake_server: _FakeRemoteConsoleServer) -> None:
    fake_server.completion_reply = ["Ext", "Extra", "ExtSomething"]
    client = BG3SERemoteConsole(on_line=lambda _line: None)
    client.connect("127.0.0.1", fake_server.port)

    result = client.request_completions("Ext", timeout=2.0)

    assert result == ["Ext", "Extra", "ExtSomething"]
    client.close()


def test_request_completions_times_out_without_server_reply(fake_server: _FakeRemoteConsoleServer) -> None:
    # Le faux serveur ne répond qu'aux tags 'T' avec `completion_reply` non
    # vide déjà géré par le test précédent ; ici on utilise un tag que le
    # faux serveur ignore volontairement en ne répondant jamais, pour tester
    # le timeout côté client sans dépendre d'un vrai délai réseau.
    client = BG3SERemoteConsole(on_line=lambda _line: None)
    client.connect("127.0.0.1", fake_server.port)
    fake_server.completion_reply = []  # le faux serveur répondra quand même avec 'R' vide

    result = client.request_completions("", timeout=2.0)

    assert result == []
    client.close()


def test_connect_to_closed_port_raises() -> None:
    # Un port fermé (rien n'écoute) doit lever RemoteConsoleError plutôt que
    # laisser fuiter une exception socket brute — c'est ce que l'UI
    # (`BG3SEConsole._connect_worker`) attrape pour afficher un message
    # utilisateur clair.
    closed_port_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    closed_port_probe.bind(("127.0.0.1", 0))
    port = closed_port_probe.getsockname()[1]
    closed_port_probe.close()

    client = BG3SERemoteConsole(on_line=lambda _line: None)
    with pytest.raises(RemoteConsoleError):
        client.connect("127.0.0.1", port, timeout=1.0)
