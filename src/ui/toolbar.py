# File: src/ui/toolbar.py
"""Constructs the application's main toolbar from the action registry.

Milestone 17 rewrite. Before this milestone, ``ApplicationToolBar`` reused
``menu_bar.py``'s already-constructed ``QAction``s by reading named
attributes off it directly (``menu_bar.action_save_project``). It now asks
the shared :class:`~src.ui.actions.action_binder.ActionBinder` for the same
action by id via :meth:`~src.ui.actions.action_binder.ActionBinder.
action_for` -- the object identity guarantee that made the old approach
work (one ``QAction``, so the toolbar button and menu item are always in
identical enabled/checked state) is unchanged; only the lookup mechanism
is, since ``menu_bar.py`` no longer exposes named ``action_*`` attributes
at all.

The toolbar renders icons now (from
:class:`~src.ui.theme.icon_provider.IconProvider`, built in milestone 15
and wired into ``ActionBinder`` this milestone) rather than text-only
buttons -- the milestone-15 icon set existed for three milestones before
anything attached one to a real button.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QToolBar

from src.core.logger import get_logger
from src.ui.actions.action_binder import ActionBinder

_logger = get_logger(__name__)

# A flat, declarative id list -- `None` inserts a separator, matching
# ActionBinder.build_menu's own convention (this toolbar just doesn't use
# build_menu itself, since QToolBar.addAction takes a QAction directly and
# there is no QMenu here to hand it to).
_TOOLBAR_ACTIONS: tuple[str | None, ...] = (
    "project.new",
    "project.open",
    "project.save",
    None,
    "view.toggle_theme",
)


class ApplicationToolBar(QToolBar):
    """The application's main toolbar, built from the shared action registry.

    Args:
        parent_window: The main window this toolbar belongs to.
        binder: Supplies each ``QAction`` by id -- the same objects
            ``menu_bar.py`` (and, once open, the command palette) reference.
    """

    def __init__(self, parent_window: QMainWindow, binder: ActionBinder) -> None:
        super().__init__("Main Toolbar", parent_window)
        self.setMovable(False)
        self._build_actions(binder)
        _logger.debug("Toolbar constructed.")

    def _build_actions(self, binder: ActionBinder) -> None:
        for action_id in _TOOLBAR_ACTIONS:
            if action_id is None:
                self.addSeparator()
                continue
            self.addAction(binder.action_for(action_id))
