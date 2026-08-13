# File: src/ui/status_bar.py
"""Constructs the application's status bar.

:class:`ApplicationStatusBar` provides two independent regions,
matching ``QStatusBar``'s own distinction between transient and
permanent messages:

* A transient message area (Qt's built-in ``showMessage`` /
  ``clearMessage``), for short-lived feedback like "Project saved."
  that disappears after a timeout or the next message.
* A permanent, always-visible label for the current project's name —
  information that should stay visible rather than being pushed out by
  the next transient message.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QMainWindow, QStatusBar

from src.core.logger import get_logger

_logger = get_logger(__name__)

_DEFAULT_MESSAGE_TIMEOUT_MS = 5000


class ApplicationStatusBar(QStatusBar):
    """The application's status bar.

    Args:
        parent_window: The main window this status bar belongs to.
    """

    def __init__(self, parent_window: QMainWindow) -> None:
        super().__init__(parent_window)

        self._project_label = QLabel("No project open")
        self.addPermanentWidget(self._project_label)

        self.showMessage("Ready")
        _logger.debug("Status bar constructed.")

    def show_message(self, message: str, timeout_ms: int = _DEFAULT_MESSAGE_TIMEOUT_MS) -> None:
        """Show a transient message that clears after ``timeout_ms``.

        Args:
            message: Text to display.
            timeout_ms: How long the message stays visible before
                automatically clearing, in milliseconds. Defaults to
                :data:`_DEFAULT_MESSAGE_TIMEOUT_MS`. Pass ``0`` for a
                message that stays until explicitly replaced or
                cleared — matching ``QStatusBar.showMessage``'s own
                convention for a zero timeout.
        """
        self.showMessage(message, timeout_ms)

    def set_active_project_label(self, project_name: str | None) -> None:
        """Update the permanent project-name label.

        Args:
            project_name: Name of the currently active project, or
                ``None`` if no project is open (shown as "No project
                open" rather than an empty label, so the region is
                never blank and ambiguous about whether it failed to
                update or genuinely has nothing to show).
        """
        self._project_label.setText(project_name if project_name else "No project open")
