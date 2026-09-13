"""Garde-fou générique pour toute la famille de bugs `AttributeError:
'NoneType' object has no attribute 'render_strips'` (TODO, sections 23b/25) :

`DownloadProgressConsole` avait une méthode `_render()` qui écrasait par
erreur `Widget._render(self) -> Visual`, une méthode INTERNE de Textual
utilisée par le compositeur pour peindre le widget. Notre `_render()`
retournait `None` au lieu d'un `Visual`, ce qui faisait planter tout rendu
du widget dès qu'il devenait effectivement visible (voir
`tests/test_download_console.py`, corrigé par le commit
"fix/DownloadsTabClickBug" — renommage en `_refresh_content`).

Investigation TODO 23b : les deux occurrences de ce crash dans `crash.log`
(session du 2026-09-11) correspondent exactement à cette fenêtre — le
widget fautif (`DownloadProgressConsole`) a été introduit le 2026-09-10 et
corrigé le 2026-09-13. Aucune autre collision de méthode privée n'a été
trouvée ailleurs dans le code (voir ce test, qui balaie TOUTES les classes
Widget/Screen custom du projet, pas seulement `DownloadProgressConsole`).

Ce test généralise le garde-fou ponctuel déjà écrit pour
`DownloadProgressConsole` : il découvre dynamiquement toutes les classes
définies dans `bg3_mod_tui` qui héritent de `textual.widget.Widget` (les
`Screen`/`ModalScreen` en héritent aussi) et vérifie qu'aucune ne redéfinit
une méthode privée (préfixée `_`, pas `__`) déjà présente sur une classe de
base Textual — la même erreur de nommage pourrait se reproduire sur
n'importe quel futur widget custom sans qu'un test dédié n'existe pour lui."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from textual.widget import Widget

import bg3_mod_tui


def _import_all_submodules(package) -> None:
    """Importe récursivement tous les sous-modules d'un package pour que
    toutes les classes Widget custom soient bien chargées et visibles via
    `sys.modules`, même celles jamais importées par le point d'entrée
    principal dans ce process de test."""
    for module_info in pkgutil.walk_packages(package.__path__, prefix=package.__name__ + "."):
        try:
            importlib.import_module(module_info.name)
        except Exception:
            # Un sous-module qui échouerait à s'importer isolément (ex:
            # dépendance optionnelle absente) n'est pas la responsabilité de
            # ce garde-fou générique ; on ignore et on continue le balayage.
            continue


def _discover_custom_widget_classes() -> list[type]:
    _import_all_submodules(bg3_mod_tui)

    import sys

    seen: set[type] = set()
    for modname, mod in list(sys.modules.items()):
        if not modname.startswith("bg3_mod_tui"):
            continue
        for _name, obj in vars(mod).items():
            if (
                inspect.isclass(obj)
                and issubclass(obj, Widget)
                and obj.__module__ == modname
            ):
                seen.add(obj)
    return sorted(seen, key=lambda c: (c.__module__, c.__name__))


def test_no_custom_widget_shadows_a_private_textual_method() -> None:
    problems: list[str] = []

    for cls in _discover_custom_widget_classes():
        own_methods = {
            name: fn for name, fn in cls.__dict__.items() if inspect.isfunction(fn)
        }
        for attr in own_methods:
            if not (attr.startswith("_") and not attr.startswith("__")):
                continue
            for base in cls.__mro__[1:]:
                if base is object:
                    continue
                base_attr = base.__dict__.get(attr)
                if inspect.isfunction(base_attr):
                    problems.append(
                        f"{cls.__module__}.{cls.__qualname__} redéfinit la méthode "
                        f"privée '{attr}' déjà utilisée en interne par "
                        f"{base.__module__}.{base.__qualname__} — risque de "
                        f"reproduire le crash 'NoneType has no attribute "
                        f"render_strips' (TODO 23b/25)."
                    )
                    break

    assert not problems, "\n" + "\n".join(problems)


def test_discovery_actually_finds_custom_widgets() -> None:
    """Garde-fou du garde-fou : si la découverte dynamique se met à ne plus
    rien trouver (import cassé, renommage de package), le test précédent
    passerait silencieusement pour la mauvaise raison. On vérifie donc
    qu'elle trouve bien au moins les widgets/écrans connus du projet."""
    classes = _discover_custom_widget_classes()
    names = {cls.__name__ for cls in classes}
    assert "DownloadProgressConsole" in names
    assert "ConsoleLog" in names
    assert len(classes) >= 10
