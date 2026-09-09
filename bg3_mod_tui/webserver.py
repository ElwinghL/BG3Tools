"""Petit serveur HTTP (`python -m http.server`) exposant le dossier du
projet, pour la fonctionnalité "Web" (accès distant via l'adresse publique
configurée). Le cycle de vie est piloté par le bouton planète du TUI :
un clic démarre le serveur, le suivant l'arrête.
"""

from __future__ import annotations

import atexit
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

OnLineFn = Callable[[str], None]

_active_handles: set["WebServerHandle"] = set()
_active_handles_lock = threading.Lock()


class WebServerHandle:
    def __init__(self, process: subprocess.Popen, thread: threading.Thread) -> None:
        self.process = process
        self.thread = thread

    @property
    def is_running(self) -> bool:
        return self.process.poll() is None

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        with _active_handles_lock:
            _active_handles.discard(self)


def stop_all_servers() -> None:
    """Arrête tout serveur encore actif. À appeler à la fermeture du TUI,
    pour ne jamais laisser un `http.server` tourner en arrière-plan sans
    que l'utilisateur l'ait explicitement laissé actif."""
    with _active_handles_lock:
        handles = list(_active_handles)
    for handle in handles:
        handle.stop()


atexit.register(stop_all_servers)


def start_http_server(directory: Path, port: str, *, on_line: OnLineFn) -> WebServerHandle:
    """Démarre `python -m http.server <port> --directory <directory>`, en
    relayant sa sortie ligne par ligne à `on_line` (appelé depuis un thread
    de lecture dédié — au consommateur de revenir sur le thread UI si besoin).
    Lève `ValueError` si `port` n'est pas un port valide."""
    port_int = int(port)
    if not (1 <= port_int <= 65535):
        raise ValueError(f"Port invalide : {port}")

    args = [sys.executable, "-m", "http.server", str(port_int), "--directory", str(directory)]
    process = subprocess.Popen(
        args,
        cwd=str(directory),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def _pump() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            on_line(line.rstrip("\n"))

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()

    handle = WebServerHandle(process, thread)
    with _active_handles_lock:
        _active_handles.add(handle)
    return handle
