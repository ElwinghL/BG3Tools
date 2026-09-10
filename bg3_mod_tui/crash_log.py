"""Journal horodaté des plantages/erreurs du TUI.

Partagé entre `app.BG3ModTUIApp._handle_exception` (exceptions qui font
planter toute l'app — thread principal ou worker avec `exit_on_error=True`)
et `screens.actions.ActionsScreen.on_worker_state_changed` (erreurs de
worker `exit_on_error=False`, qui ne font PAS planter l'app mais doivent
rester tracées). Module séparé pour éviter un import circulaire entre
`app.py` et `screens/actions.py` (qui s'importent déjà l'un l'autre)."""

from __future__ import annotations

import traceback
from datetime import datetime

from bg3_mod_tui.config import CONFIG_PATH

CRASH_LOG_PATH = CONFIG_PATH.parent / "crash.log"


def log_crash(error: BaseException) -> None:
    try:
        with CRASH_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} ===\n")
            traceback.print_exception(error, file=f)
    except OSError:
        pass
