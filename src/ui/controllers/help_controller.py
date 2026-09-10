# File: src/ui/controllers/help_controller.py
"""Owns F1: resolves which manual anchor to show and keeps one :class:`ManualDialog` alive.

Moved out of ``main_window.py`` for the same "one small controller per concern" reasoning
:mod:`src.ui.controllers`'s own docstring gives for every other controller in this package --
``main_window.py`` only needs to construct this once and wire a single ``QShortcut`` to
:meth:`HelpController.show_help_for_focus`.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

from src.ui.dialogs.manual_dialog import ManualDialog
from src.ui.help.help_router import resolve_help_anchor
from src.ui.workbench.workbench import Workbench
from uadas_core.core.logger import get_logger

_logger = get_logger(__name__)

_FALLBACK_ANCHOR = "index"


class HelpController:
    """Resolves an anchor for the current keyboard focus and shows it in a shared dialog.

    Args:
        parent: The window the manual dialog is parented to.
        workbench: Read for the second-level fallback (the currently visible stage page's own
            anchor) when nothing on the focus chain itself carries one -- see
            :meth:`~src.ui.workbench.workbench.Workbench.current_page`'s own docstring for why
            this case is real (focus in a dock, not inside the visible stage page).
    """

    def __init__(self, parent: QWidget, workbench: Workbench) -> None:
        self._parent = parent
        self._workbench = workbench
        # Lazily constructed on first use, then kept alive for the rest of the session -- see
        # ManualDialog's own docstring for why a fresh instance per F1 press would be wrong
        # (it would forget which page was last shown, and pop a new window on top each time).
        self._dialog: ManualDialog | None = None
        # QKeySequence.StandardKey.HelpContents, not the literal string "F1" -- matches the
        # plan's own wording and resolves to whatever a given platform's real "show help" key
        # is (F1 on Windows/Linux). A plain QShortcut, not a QAction/ActionSpec: F1 is a
        # window-wide keyboard shortcut with no menu/toolbar/palette presence of its own,
        # unlike every registered action in uadas_core.actions.action_registry.
        self._shortcut = QShortcut(
            QKeySequence(QKeySequence.StandardKey.HelpContents), parent
        )
        self._shortcut.activated.connect(self.show_help_for_focus)

    def show_help_for_focus(self) -> None:
        """F1's handler: resolve an anchor for the current focus and show it.

        The three-step fallback chain the plan documents: the focused widget's own (or an
        ancestor's, or a focused toolbar button/menu item's) stamped anchor; failing that, the
        workbench's currently visible stage page; failing that (no stage page is showing --
        the welcome page, or no project at all), the manual's own index page.
        """
        anchor = resolve_help_anchor(QApplication.focusWidget())
        if anchor is None:
            current_page = self._workbench.current_page()
            if current_page is not None:
                anchor = current_page.help_anchor
        self.show_manual(anchor or _FALLBACK_ANCHOR)

    def show_manual(self, anchor: str) -> None:
        """Show ``anchor`` in the shared manual dialog, constructing it on first use."""
        if self._dialog is None:
            self._dialog = ManualDialog(self._parent)
        self._dialog.show_anchor(anchor)
        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()
        _logger.debug("Manual opened at anchor %r.", anchor)
