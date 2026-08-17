# File: src/ui/toolbar.py
"""Constructs the application's main toolbar.

:class:`ApplicationToolBar` does not create its own ``QAction``
instances. Instead, it receives the menu bar's already-constructed
actions (see :class:`~src.ui.menu_bar.ApplicationMenuBar`) and adds a
subset of them here, so a single click in the toolbar and the
corresponding menu item trigger the exact same ``QAction`` — meaning
identical behavior, enabled/disabled state, and shortcut, with no risk
of the toolbar silently drifting out of sync with the menu because two
separate ``QAction`` objects for the same operation were connected to
two separate handlers.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow, QToolBar

from src.core.logger import get_logger
from src.ui.menu_bar import ApplicationMenuBar

_logger = get_logger(__name__)


class ApplicationToolBar(QToolBar):
    """The application's main toolbar, built from the menu bar's actions.

    Args:
        parent_window: The main window this toolbar belongs to.
        menu_bar: The already-constructed
            :class:`~src.ui.menu_bar.ApplicationMenuBar` whose actions
            this toolbar reuses. Constructing the menu bar first is a
            requirement, not a convenience — this class has nothing to
            add to the toolbar without it.
    """

    def __init__(
        self, parent_window: QMainWindow, menu_bar: ApplicationMenuBar
    ) -> None:
        super().__init__("Main Toolbar", parent_window)
        self.setMovable(False)
        self._build_actions(menu_bar)
        _logger.debug("Toolbar constructed.")

    def _build_actions(self, menu_bar: ApplicationMenuBar) -> None:
        self.addAction(menu_bar.action_new_project)
        self.addAction(menu_bar.action_open_project)
        self.addAction(menu_bar.action_save_project)
        self.addSeparator()
        self.addAction(menu_bar.action_undo)
        self.addAction(menu_bar.action_redo)
        self.addSeparator()
        self.addAction(menu_bar.action_toggle_theme)
