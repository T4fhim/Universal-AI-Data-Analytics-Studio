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

from PySide6.QtWidgets import QLabel, QMainWindow, QProgressBar, QStatusBar

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

        self._project_label = QLabel(self.tr("No project open"))
        self.addPermanentWidget(self._project_label)

        # Busy indicator (milestone 6): indeterminate (0/0 range) rather
        # than a real percentage, since most background tasks wrapped by
        # src.workers.BaseWorker (dataset reads, dashboard renders) have
        # no natural sub-steps to report progress against — this widget
        # exists to make "something is happening on a worker thread"
        # visible, not to report exact completion. Retained as an
        # instance attribute per this repo's Live Widget References
        # convention (see the pyside6-development skill) so
        # show_busy/hide_busy can update it without reconstructing it.
        self._busy_indicator = QProgressBar(self)
        self._busy_indicator.setRange(0, 0)
        self._busy_indicator.setMaximumWidth(120)
        self._busy_indicator.setTextVisible(False)
        self._busy_indicator.setVisible(False)
        self.addPermanentWidget(self._busy_indicator)

        self.showMessage("Ready")
        _logger.debug("Status bar constructed.")

    def show_busy(self, message: str = "Working…") -> None:
        """Show the indeterminate busy indicator and a transient status message.

        Args:
            message: Shown via :meth:`show_message` alongside the
                indicator, with a zero timeout (stays until
                :meth:`hide_busy` or the next message replaces it)
                since a busy operation's duration isn't known in
                advance.

        Resets the indicator to indeterminate (0/0) range even if a
        previous :meth:`show_progress` call left it determinate — a new
        busy operation starting should not inherit a stale percentage from
        whatever the last one reported.
        """
        self._busy_indicator.setRange(0, 0)
        self._busy_indicator.setVisible(True)
        self.show_message(message, timeout_ms=0)

    def show_progress(self, percent: int, message: str = "") -> None:
        """Switch the busy indicator to determinate and report ``percent``.

        Args:
            percent: 0-100, matching
                :attr:`~src.workers.base_worker.WorkerSignals.progress`'s
                own contract — connect a worker's ``signals.progress``
                directly to this method.
            message: Shown alongside the percentage via
                :meth:`show_message`, with a zero timeout for the same
                reason :meth:`show_busy` uses one. Skipped entirely when
                empty, so a caller reporting bare percentage with no
                status text does not blank out whatever message
                :meth:`show_busy` already set.

        Milestone 17: no wrapped callable in this codebase calls its
        ``progress_callback`` yet (confirmed by grep — every existing
        ``BaseWorker(..., report_progress=True)`` call site remains
        ``report_progress=False``), so this method exists and every
        current worker's ``signals.progress`` is connected to it, but
        nothing currently emits it. That is deliberate, incremental
        wiring, not a partial implementation: milestone 25 is where the
        first real caller (``compare_forecast_models``) gains a
        ``progress_callback`` parameter. Calling this method before that
        lands is harmless — it simply never happens.
        """
        self._busy_indicator.setRange(0, 100)
        self._busy_indicator.setValue(max(0, min(100, percent)))
        if message:
            self.show_message(message, timeout_ms=0)

    def hide_busy(self) -> None:
        """Hide the busy indicator.

        Does not clear the transient message area — callers typically
        follow this with their own ``show_message`` reporting the
        operation's outcome (e.g. "Loaded dataset: ...").
        """
        self._busy_indicator.setVisible(False)

    def show_message(
        self, message: str, timeout_ms: int = _DEFAULT_MESSAGE_TIMEOUT_MS
    ) -> None:
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
