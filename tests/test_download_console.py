"""Régression pour le bug UI "clic sur l'onglet Téléchargements" (TODO,
section sur la vue par onglets, sous-tâche 7c) : `DownloadProgressConsole`
(`bg3_mod_tui/widgets/download_console.py`) définissait une méthode
`_render()` qui écrasait sans le vouloir `Widget._render(self) -> Visual`,
une méthode INTERNE de Textual utilisée par le compositeur pour obtenir le
`Visual` à peindre. Notre `_render()` retournait `None` (au lieu d'un
`Visual`), ce qui faisait planter tout rendu du widget avec
`AttributeError: 'NoneType' object has no attribute 'render_strips'` dès
qu'il devenait effectivement visible — ce qui n'arrive qu'au premier
affichage de son `TabPane` "Téléchargements" dans `ActionsScreen`, d'où un
plantage de toute l'appli au clic sur cet onglet précis, et nulle part
ailleurs (les 3 autres onglets ne montent jamais ce widget).

Ce test monte le widget seul dans une app Textual minimale et force un
rendu complet (`pilot.pause()` déclenche un premier passage du
compositeur) : sans la régression, cela suffit à reproduire le crash sans
avoir besoin de simuler un clic sur l'onglet lui-même (le widget crashe dès
qu'il doit être peint, qu'il devienne visible via un clic ou autrement)."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from bg3_mod_tui.widgets.download_console import DownloadProgressConsole


class _MiniApp(App):
    def compose(self) -> ComposeResult:
        yield DownloadProgressConsole(id="downloads-progress")


def test_download_progress_console_renders_without_crashing() -> None:
    async def run() -> None:
        app = _MiniApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            console = app.query_one(DownloadProgressConsole)
            # Simule un cycle de mise à jour de progression complet
            # (démarrage, mise à jour, fin) pour s'assurer que
            # `_refresh_content` (l'ancien `_render` renommé) fonctionne
            # aussi bien à vide qu'avec des slots actifs.
            console.update_progress("nexus-1-1", "mod.zip", 512, 1024)
            await pilot.pause()
            console.update_progress("nexus-1-1", "mod.zip", None, None)
            await pilot.pause()
            console.clear()
            await pilot.pause()

    asyncio.run(run())


def test_download_progress_console_does_not_shadow_private_textual_api() -> None:
    """Garde-fou explicite contre une récidive : `DownloadProgressConsole`
    ne doit redéfinir aucune méthode privée de `Widget` (préfixée `_`) déjà
    utilisée en interne par Textual pour le rendu/cycle de vie, sous peine
    de reproduire silencieusement ce même type de plantage."""
    from textual.widget import Widget

    assert DownloadProgressConsole._render is Widget._render
