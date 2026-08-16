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

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
)

from src.core.logger import get_logger
from src.ui.widgets.chart_view import ChartView
from src.ui.widgets.chat_panel import ChatPanel

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
        self.dock_ai_chat = self._build_ai_chat_dock()

        parent_window.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_project_explorer
        )
        parent_window.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_dataset_explorer
        )
        parent_window.tabifyDockWidget(
            self.dock_project_explorer, self.dock_dataset_explorer
        )

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
        parent_window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.dock_chart
        )

        # Milestone 10: the AI chat panel — stacked below the chart dock
        # in the same (right) area rather than tabbed with it, so a
        # chart and an in-progress conversation can both stay visible
        # at once (splitting vertically is Qt's default for two docks
        # added to the same area without an explicit tabifyDockWidget
        # call, matching how Project/Dataset Explorer and Console/Log
        # are *deliberately* tabbed above while this pair is not).
        parent_window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.dock_ai_chat
        )
        parent_window.splitDockWidget(
            self.dock_chart, self.dock_ai_chat, Qt.Orientation.Vertical
        )

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
        # Stored as self._dataset_tree_widget (not just a local
        # variable, unlike the project-explorer dock's list widget
        # above) because milestone 2's "Open Dataset" action needs to
        # push live updates into this dock after this constructor has
        # already returned — see refresh_dataset_list below, which
        # main_window.py calls whenever WorkspaceService's set of
        # loaded datasets changes.
        #
        # Milestone 10: a QTreeWidget rather than the original flat
        # QListWidget, so a cleaned/derived dataset nests under the
        # dataset it came from instead of appearing as an unrelated
        # sibling — this is the same parent_dataset_id lineage
        # WorkspaceService.get_lineage/get_children already expose,
        # just made visible rather than only queryable in code.
        self._dataset_tree_widget = QTreeWidget(dock)
        self._dataset_tree_widget.setHeaderHidden(True)
        self._show_no_datasets_placeholder()
        dock.setWidget(self._dataset_tree_widget)
        return dock

    def _show_no_datasets_placeholder(self) -> None:
        self._dataset_tree_widget.clear()
        QTreeWidgetItem(self._dataset_tree_widget, ["(No datasets loaded)"])

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
        the tree each time rather than diffing against the previous
        contents — matching the same rebuild-not-diff approach
        :meth:`~src.ui.menu_bar.ApplicationMenuBar.update_recent_projects_menu`
        already uses for the same reason: the list is expected to stay
        small, and full-rebuild is simpler and less error-prone than
        incremental widget-state maintenance for a list this size.

        Datasets whose ``parent_dataset_id`` points at another dataset
        in ``datasets`` are nested as tree children of that parent,
        recursively, so a chain of cleaning operations reads as a
        lineage rather than a flat, unordered list. A dataset whose
        ``parent_dataset_id`` is set but not present in ``datasets``
        (the parent was closed — see the "non-cascading close" rule in
        CLAUDE.md's Workspace model section) is rendered at the top
        level rather than dropped, since it is still a real, openable
        dataset regardless of whether its lineage is fully visible
        right now.
        """
        self._dataset_tree_widget.clear()
        if not datasets:
            self._show_no_datasets_placeholder()
            return

        by_id = {dataset.dataset_id: dataset for dataset in datasets}
        items_by_id: dict[str, QTreeWidgetItem] = {}

        def _label(dataset) -> str:
            return f"{dataset.name} ({dataset.row_count} rows × {dataset.column_count} cols)"

        def _build_item(dataset) -> QTreeWidgetItem:
            if dataset.dataset_id in items_by_id:
                return items_by_id[dataset.dataset_id]
            parent_id = dataset.parent_dataset_id
            if parent_id is not None and parent_id in by_id:
                parent_item = _build_item(by_id[parent_id])
                item = QTreeWidgetItem(parent_item, [_label(dataset)])
            else:
                item = QTreeWidgetItem(self._dataset_tree_widget, [_label(dataset)])
            items_by_id[dataset.dataset_id] = item
            return item

        for dataset in datasets:
            _build_item(dataset)
        self._dataset_tree_widget.expandAll()

    def _build_console_dock(self) -> QDockWidget:
        dock = QDockWidget("Console", self._parent_window)
        dock.setObjectName("dockConsole")
        # Milestone 10: stored as self._console_text_widget (previously
        # a local variable, since nothing wrote to it after
        # construction) — append_console_message below needs to reach
        # it from outside __init__, the same reason
        # self._dataset_tree_widget and self._chart_tabs are retained.
        self._console_text_widget = QPlainTextEdit(dock)
        self._console_text_widget.setReadOnly(True)
        self._console_text_widget.setPlaceholderText(
            "Pipeline stages, worker activity, and tool calls will appear here."
        )
        dock.setWidget(self._console_text_widget)
        return dock

    def append_console_message(self, text: str) -> None:
        """Append one timestamped line to the Console dock.

        Called by :mod:`src.ui.main_window` for the same events already
        surfaced elsewhere (status-bar messages, AI tool activity,
        analysis-pipeline stages) — the Console dock's job is to be the
        one place a durable, scrollable record of *everything* that
        happened accumulates, since the status bar's messages are
        transient and the AI chat panel's tool-activity notes only
        cover assistant-driven actions, not menu-driven ones like
        "Open Dataset" or "Create Dashboard".
        """
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        self._console_text_widget.appendPlainText(f"{timestamp} | {text}")

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
        dock = QDockWidget("Charts", self._parent_window)
        dock.setObjectName("dockChart")
        # Milestone 10: a QTabWidget of independent ChartView instances,
        # replacing the single-ChartView-overwrites-previous behavior —
        # each call to display_chart() below adds a new tab rather than
        # replacing whatever was already shown, so a dashboard, a
        # dataset visualization, and an AI-built chart (milestone 9's
        # build_chart tool) can all stay open for comparison instead of
        # each one silently discarding the last.
        self._chart_tabs = QTabWidget(dock)
        self._chart_tabs.setTabsClosable(True)
        self._chart_tabs.tabCloseRequested.connect(self._on_chart_tab_close_requested)
        dock.setWidget(self._chart_tabs)
        return dock

    def _on_chart_tab_close_requested(self, index: int) -> None:
        widget = self._chart_tabs.widget(index)
        self._chart_tabs.removeTab(index)
        if widget is not None:
            # Qt's removeTab() does not itself destroy the removed
            # widget — without this, each closed chart tab would leak
            # its QWebEngineView (ChartView) rather than being freed.
            widget.deleteLater()

    def display_chart(self, figure, name: str | None = None) -> None:
        """Add ``figure`` as a new tab in the chart dock and bring it to the foreground.

        Args:
            figure: A Plotly figure — see
                :meth:`~src.ui.widgets.chart_view.ChartView.
                display_figure` for the accepted types.
            name: Tab label. Defaults to ``"Chart N"`` (using the
                current tab count) so call sites written before
                milestone 10 keep working without passing a name —
                callers that have a meaningful name (a
                ``Visualization.name``, a dashboard title) should pass
                it for a more useful tab label.
        """
        chart_view = ChartView(self._chart_tabs)
        chart_view.display_figure(figure)
        tab_label = name or f"Chart {self._chart_tabs.count() + 1}"
        index = self._chart_tabs.addTab(chart_view, tab_label)
        self._chart_tabs.setCurrentIndex(index)
        self.dock_chart.raise_()
        self.dock_chart.show()

    def _build_ai_chat_dock(self) -> QDockWidget:
        dock = QDockWidget("AI Assistant", self._parent_window)
        dock.setObjectName("dockAiChat")
        # Stored as self.chat_panel (public, unlike most of this
        # class's per-dock widgets) because main_window.py needs to
        # connect send_button.clicked and append conversation turns
        # after construction — the same reason self._dataset_list_widget
        # is retained above, just public since the caller here is a
        # different module rather than a method on this same class.
        self.chat_panel = ChatPanel(dock)
        dock.setWidget(self.chat_panel)
        return dock

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
            self.dock_ai_chat.toggleViewAction(),
        ]
