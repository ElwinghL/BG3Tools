"""Point d'entrée du TUI."""

from __future__ import annotations

import signal
import sys


def _handle_sigterm(signum: int, frame: object) -> None:
    # SIGTERM termine le processus sans exécuter les gestionnaires `atexit`
    # (contrairement à SIGINT/Ctrl+C, qui lève KeyboardInterrupt) : on le
    # convertit ici en SystemExit pour dérouler la fermeture normalement
    # (et donc terminer les processus d'extraction encore en cours).
    raise SystemExit(0)


def run() -> None:
    from bg3_mod_tui.app import BG3ModTUIApp

    signal.signal(signal.SIGTERM, _handle_sigterm)

    app = BG3ModTUIApp()
    app.run()


if __name__ == "__main__":
    sys.exit(run())
