"""Client TCP pour la console BG3SE distante (section 11 du TODO).

Parle au pont bidirectionnel ajouté côté C++ dans le fork BG3SE
(`Tools/BG3 Script Extender/BG3Extender/Extender/Shared/RemoteConsole.{h,cpp}`,
branche locale non poussée `feat/RemoteConsoleSocket` du sous-module) : un
petit protocole texte à base de trames préfixées par une longueur, réutilisant
le même formatage que `SocketInterface::SendProtobufMessage` déjà utilisé par
le débogueur Osiris/Lua existant dans BG3SE.

Le socket écoute en boucle locale (127.0.0.1) DANS le process Windows du jeu
sous Proton — mais comme Wine implémente winsock directement au-dessus de la
pile réseau de l'hôte Linux, ce port est atteignable tel quel depuis ce script
Python (pas besoin de passer par le préfixe Wine, contrairement à un named
pipe Windows classique qui resterait, lui, interne au wineserver).

Format de trame (voir RemoteConsole.h côté C++ pour les détails) :
    <uint32 little-endian: taille totale de la trame, entête inclus>
    <1 octet : tag>
    <reste : payload UTF-8>

Tags :
    Serveur -> client : 'L' (une ligne de sortie console), 'R' (réponse de
    complétion, candidats séparés par '\\x1f', éventuellement vide)
    Client -> serveur : 'C' (une commande complète), 'T' (requête de
    complétion pour le préfixe en cours de saisie)

NON TESTÉ contre un vrai process de jeu : aucun environnement Windows/BG3SE
buildé n'était disponible pour valider ce client de bout en bout (voir
.claude/TODO.md section 11 pour le détail du blocage côté build C++). Le
protocole implémenté ici est le miroir exact de ce qu'écrit
`RemoteConsole.cpp`."""

from __future__ import annotations

import socket
import struct
import threading
from dataclasses import dataclass
from typing import Callable

_HEADER_SIZE = 4
_TAG_LINE = b"L"
_TAG_COMPLETIONS = b"R"
_TAG_COMMAND = b"C"
_TAG_COMPLETE_REQUEST = b"T"
_COMPLETION_SEPARATOR = "\x1f"

# Délai raisonnable pour une requête de complétion : elle implique un aller
# retour jusqu'au thread du jeu côté serveur (SubmitTaskAndWait sur l'état
# Lua), donc plus long qu'un simple ping réseau local, mais doit rester assez
# court pour ne pas geler la saisie si le jeu est dans un état qui ne peut pas
# traiter la requête (ex : ni serveur ni client Lua initialisé).
DEFAULT_COMPLETION_TIMEOUT = 2.0


class RemoteConsoleError(Exception):
    """Erreur de connexion ou de protocole avec la console BG3SE distante."""


@dataclass
class _PendingCompletion:
    event: threading.Event
    result: list[str] | None = None


class BG3SERemoteConsole:
    """Connexion à un pont RemoteConsole côté jeu.

    Usage : `connect()` puis `send_command()` pour exécuter du Lua/des
    commandes spéciales, `request_completions()` pour l'auto-complétion
    (bloquant, à appeler depuis un thread de worker — jamais depuis le
    thread UI Textual). Les lignes de sortie reçues du serveur sont
    poussées au `on_line` fourni au constructeur, depuis le thread de
    lecture interne (donc lui-même déjà responsable de rejoindre le thread
    UI si besoin, comme les autres callbacks `log` de `actions.py`)."""

    def __init__(self, on_line: Callable[[str], None], on_disconnect: Callable[[], None] | None = None) -> None:
        self._on_line = on_line
        self._on_disconnect = on_disconnect
        self._sock: socket.socket | None = None
        self._recv_thread: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._pending_completion: _PendingCompletion | None = None
        self._pending_lock = threading.Lock()
        self._closed = threading.Event()

    def connect(self, host: str, port: int, timeout: float = 5.0) -> None:
        """Ouvre la connexion et démarre le thread de lecture. Lève
        `RemoteConsoleError` si la connexion échoue (jeu non lancé, BG3SE
        non chargé, ou patch RemoteConsole absent de ce build)."""
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
        except OSError as exc:
            raise RemoteConsoleError(
                f"Connexion à la console BG3SE ({host}:{port}) impossible : {exc}. "
                "Le jeu est-il lancé avec un BG3SE incluant le patch RemoteConsole ?"
            ) from exc

        sock.settimeout(None)
        self._sock = sock
        self._closed.clear()
        self._recv_thread = threading.Thread(target=self._recv_loop, name="bg3se-remote-console-recv", daemon=True)
        self._recv_thread.start()

    def close(self) -> None:
        self._closed.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        # Débloque une éventuelle complétion en attente plutôt que de la
        # laisser expirer sur son propre timeout.
        with self._pending_lock:
            pending = self._pending_completion
            self._pending_completion = None
        if pending is not None:
            pending.result = []
            pending.event.set()

    @property
    def connected(self) -> bool:
        return self._sock is not None and not self._closed.is_set()

    def send_command(self, text: str) -> None:
        """Envoie une commande (ligne complète) — même chemin que le prompt
        de la console Win32 native côté serveur (`DebugConsole::HandleCommand`,
        via `RemoteConsole::SetCommandHandler`)."""
        self._send_frame(_TAG_COMMAND, text)

    def request_completions(self, partial: str, timeout: float = DEFAULT_COMPLETION_TIMEOUT) -> list[str]:
        """Demande les complétions pour `partial` et BLOQUE jusqu'à la
        réponse ou l'expiration de `timeout`. Une seule requête de
        complétion peut être en vol à la fois (suffisant pour un usage
        interactif ligne par ligne) ; une nouvelle requête pendant qu'une
        autre est en cours annule silencieusement l'attente de la
        précédente côté appelant (elle recevra `[]` à son timeout)."""
        pending = _PendingCompletion(event=threading.Event())
        with self._pending_lock:
            self._pending_completion = pending

        self._send_frame(_TAG_COMPLETE_REQUEST, partial)

        if not pending.event.wait(timeout):
            with self._pending_lock:
                if self._pending_completion is pending:
                    self._pending_completion = None
            return []

        return pending.result or []

    # -- Interne --------------------------------------------------------

    def _send_frame(self, tag: bytes, text: str) -> None:
        sock = self._sock
        if sock is None:
            raise RemoteConsoleError("Console BG3SE non connectée.")

        payload = tag + text.encode("utf-8")
        frame = struct.pack("<I", len(payload) + _HEADER_SIZE) + payload

        with self._send_lock:
            try:
                sock.sendall(frame)
            except OSError as exc:
                raise RemoteConsoleError(f"Échec d'envoi vers la console BG3SE : {exc}") from exc

    def _recv_loop(self) -> None:
        sock = self._sock
        buf = b""
        try:
            while sock is not None and not self._closed.is_set():
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buf += chunk

                while len(buf) >= _HEADER_SIZE:
                    (frame_len,) = struct.unpack_from("<I", buf, 0)
                    if frame_len < _HEADER_SIZE:
                        # Trame corrompue/protocole incompatible : on ne peut
                        # plus resynchroniser de façon fiable sur ce flux.
                        raise RemoteConsoleError("Trame RemoteConsole invalide (longueur < entête).")
                    if len(buf) < frame_len:
                        break

                    payload = buf[_HEADER_SIZE:frame_len]
                    buf = buf[frame_len:]
                    self._handle_payload(payload)
        except OSError:
            pass
        except RemoteConsoleError:
            pass
        finally:
            self._closed.set()
            if self._on_disconnect is not None:
                try:
                    self._on_disconnect()
                except Exception:
                    pass

    def _handle_payload(self, payload: bytes) -> None:
        if not payload:
            return

        tag = payload[:1]
        text = payload[1:].decode("utf-8", errors="replace")

        if tag == _TAG_LINE:
            self._on_line(text)
        elif tag == _TAG_COMPLETIONS:
            candidates = text.split(_COMPLETION_SEPARATOR) if text else []
            with self._pending_lock:
                pending = self._pending_completion
                self._pending_completion = None
            if pending is not None:
                pending.result = candidates
                pending.event.set()
        # Tag inconnu : ignoré (avant-poste de compatibilité protocolaire,
        # comme côté serveur — voir RemoteConsole.cpp).
