"""Point d'entrée du TUI."""

from __future__ import annotations

import sys


def run() -> None:
    from bg3_mod_tui.app import BG3ModTUIApp

    app = BG3ModTUIApp()
    app.run()


if __name__ == "__main__":
    sys.exit(run())
