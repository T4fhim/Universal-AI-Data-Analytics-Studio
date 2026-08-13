# File: src/ui/dock_manager.py
"""Constructs and manages the application's dockable panels.

:class:`DockManager` builds the four dock widgets the original
specification calls for — Project Explorer, Dataset Explorer, Console,
and a Logging panel — and docks them onto the main window at
reasonable default positions. Each dock's actual content in this
milestone is a placeholder ``QListWidget`` or ``QPlainTextEdit`` with
no data behind it yet; wiring these to real project/dataset data is
out of scope here (that belongs to milestones that build the readers
and data-model layers) and populating them with fake sample data would
misrepresent the application's current state as further along than it
is. What this milestone delivers is the docking *infrastructure* —
resizable, closable, re-orderable panels with working visibility
toggles — which is a real, complete piece of functionality on its own.

The Logging panel is the one dock with genuine behavior already: it
attaches a ``logging.Handler`` to the root logger so that every log
message the application emits (through
:func:`~src.core.logger.get_logger`, used throughout this codebase)
appears in this panel live, not just in the rotating file and console
output logger.py already provides.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
)

from src.core.logger import get_logger
from src.ui.widgets.chart_view import ChartView

_logger = get_logger(__name__)


class _QtLogHandler(logging.Handler):
    """A ``logging.Handler`` that appends formatted records to a QPlainTextEdit.

    Kept as a private, module-level class rather than a method on
    :class:`DockManager` because ``logging.Handler`` has its own
    lifecycle (attached to and eventually removable from a logger)
    that is cleaner to reason about as a standalone object than as
    behavior mixed into the dock-construction class.
    """

    def __init__(self, text_widget: QPlainTextEdit) -> None:
        super().__init__()
        self._text_widget = text_widget

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self._text_widget.appendPlainText(message)
        except Exception:
            # A logging handler must never raise — doing so risks
            # taking down whatever code just tried to log a message,
            # which is almost always worse than a dropped log line in
            # the on-screen panel (the rotating file handler from
            # logger.py is unaffected either way, since handlers are
            # independent).
            self.handleError(record)


class DockManager:
    """Constructs and owns the application's dock widgets.

    Args:
        parent_window: The main window docks are attached to.
    """

    def __init__(self, parent_window: QMainWindow) -> None:
        self._parent_window = parent_window

        self.dock_project_explorer = self._build_project_explorer_dock()
        self.dock_dataset_explorer = self._build_dataset_explorer_dock()
        self.dock_console = self._build_console_dock()
        self.dock_logging = self._build_logging_dock()
        self.dock_chart = self._build_chart_dock()

        parent_window.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_project_explorer
        )
        parent_window.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_dataset_explorer
        )
        parent_window.tabifyDockWidget(self.dock_project_explorer, self.dock_dataset_explorer)

        parent_window.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_console
        )
        parent_window.addDockWidget(
            Qt.DockWidgetArea.BottomDockWidgetArea, self.dock_logging
        )
        parent_window.tabifyDockWidget(self.dock_console, self.dock_logging)

        # Right side, not tabbed with anything: a chart is significant
        # enough content that it should be immediately visible once
        # populated, not hidden behind a tab click the way
        # Project/Dataset Explorer or Console/Log reasonably are.
        parent_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_chart)

        self.dock_project_explorer.raise_()
        self.dock_console.raise_()

        _logger.debug("Dock widgets constructed and attached to main window.")

    def _build_project_explorer_dock(self) -> QDockWidget:
        dock = QDockWidget("Project Explorer", self._parent_window)
        dock.setObjectName("dockProjectExplorer")
        list_widget = QListWidget(dock)
        list_widget.addItem("(No project open)")
        dock.setWidget(list_widget)
        return dock

    def _build_dataset_explorer_dock(self) -> QDockWidget:
        dock = QDockWidget("Dataset Explorer", self._parent_window)
        dock.setObjectName("dockDatasetExplorer")
        # Stored as self._dataset_list_widget (not just a local
        # variable, unlike the project-explorer dock's list widget
        # above) because milestone 2's "Open Dataset" action needs to
        # push live updates into this dock after this constructor has
        # already returned — see refresh_dataset_list below, which
        # main_window.py calls whenever WorkspaceService's set of
        # loaded datasets changes.
        self._dataset_list_widget = QListWidget(dock)
        self._show_no_datasets_placeholder()
        dock.setWidget(self._dataset_list_widget)
        return dock

    def _show_no_datasets_placeholder(self) -> None:
        self._dataset_list_widget.clear()
        self._dataset_list_widget.addItem("(No datasets loaded)")

    def refresh_dataset_list(self, datasets: list) -> None:
        """Rebuild the Dataset Explorer dock's contents from the current dataset list.

        Args:
            datasets: The datasets to display, typically the return
                value of
                :meth:`~src.services.workspace_service.WorkspaceService.list_datasets`.
                Typed as a plain ``list`` rather than
                ``list[Dataset]`` to avoid this module importing
                ``src.services.workspace_service`` for a type hint
                alone — ``DockManager`` has no other reason to depend
                on the services layer, and a ``TYPE_CHECKING``-only
                import for one parameter's annotation was judged not
                worth the added import for a private, UI-internal
                method whose caller (``main_window.py``) already
                knows the real type.

        Called by :mod:`src.ui.main_window` after any operation that
        adds or removes a dataset from the workspace (currently: after
        a successful "Open Dataset" action). This clears and rebuilds
        the list each time rather than diffing against the previous
        contents — matching the same rebuild-not-diff approach
        :meth:`~src.ui.menu_bar.ApplicationMenuBar.update_recent_projects_menu`
        already uses for the same reason: the list is expected to stay
        small, and full-rebuild is simpler and less error-prone than
        incremental widget-state maintenance for a list this size.
        """
        self._dataset_list_widget.clear()
        if not datasets:
            self._show_no_datasets_placeholder()
            return
        for dataset in datasets:
            row_count = dataset.row_count
            column_count = dataset.column_count
            self._dataset_list_widget.addItem(
                f"{dataset.name} ({row_count} rows × {column_count} cols)"
            )

    def _build_console_dock(self) -> QDockWidget:
        dock = QDockWidget("Console", self._parent_window)
        dock.setObjectName("dockConsole")
        text_widget = QPlainTextEdit(dock)
        text_widget.setReadOnly(True)
        text_widget.setPlaceholderText(
            "Console output will appear here in a later milestone."
        )
        dock.setWidget(text_widget)
        return dock

    def _build_logging_dock(self) -> QDockWidget:
        dock = QDockWidget("Log", self._parent_window)
        dock.setObjectName("dockLogging")
        text_widget = QPlainTextEdit(dock)
        text_widget.setReadOnly(True)

        handler = _QtLogHandler(text_widget)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logging.getLogger().addHandler(handler)
        self._log_handler = handler  # kept alive; see remove_log_handler

        dock.setWidget(text_widget)
        return dock

    def _build_chart_dock(self) -> QDockWidget:
        dock = QDockWidget("Chart", self._parent_window)
        dock.setObjectName("dockChart")
        self._chart_view = ChartView(dock)
        dock.setWidget(self._chart_view)
        return dock

    def display_chart(self, figure) -> None:
        """Render ``figure`` into the chart dock and bring it to the foreground.

        Args:
            figure: A Plotly figure — see
                :meth:`~src.ui.widgets.chart_view.ChartView.
                display_figure` for the accepted types.
        """
        self._chart_view.display_figure(figure)
        self.dock_chart.raise_()
        self.dock_chart.show()

    def remove_log_handler(self) -> None:
        """Detach the logging-panel handler from the root logger.

        Should be called before the main window closes. Without this,
        the root logger would keep a reference to a handler wrapping a
        destroyed Qt widget, and any log call after window close would
        raise when the handler tried to write to a widget that no
        longer exists.
        """
        logging.getLogger().removeHandler(self._log_handler)
        _logger.debug("Logging-panel handler removed from root logger.")

    def view_menu_toggle_actions(self) -> list:
        """Return each dock's built-in ``toggleViewAction()``, in display order.

        These are the actions :mod:`src.ui.main_window` adds to the
        menu bar's View menu so the user can show/hide each panel.
        Returned as a plain list rather than added to the menu
        directly from here, since this class does not hold a
        reference to the menu bar — see the note in
        :mod:`src.ui.menu_bar` about why the View menu's dock toggles
        are populated by ``main_window.py`` rather than by either
        class independently.
        """
        return [
            self.dock_project_explorer.toggleViewAction(),
            self.dock_dataset_explorer.toggleViewAction(),
            self.dock_console.toggleViewAction(),
            self.dock_logging.toggleViewAction(),
            self.dock_chart.toggleViewAction(),
        ]
