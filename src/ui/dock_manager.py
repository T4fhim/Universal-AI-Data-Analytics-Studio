# File: src/ui/dock_manager.py
"""Constructs and manages the application's dockable panels.

:class:`DockManager` builds every dock widget the application uses -- Dataset Explorer,
Console, Logging, Charts, Data Table, and AI Assistant -- and docks them onto the main window at
reasonable default positions.

Milestone 20 note: the original Project Explorer dock is deleted here, not merely hidden -- it
never worked (its ``QListWidget`` always read ``"(No project open)"`` and nothing ever wired it
to anything real; confirmed by this overhaul's own audit) and its one job, naming the open
project, is absorbed into Dataset Explorer as a top-level "Project" node (see
:meth:`DockManager.set_project_label`). The Charts dock is demoted to default-hidden in the same
milestone -- a chart's primary home is now the workbench's Visualize stage page (milestone 24),
not a dock that claims screen space before any chart exists. Both changes are named explicitly
in the plan's A3 dock-disposition table as this overhaul's only user-visible dock removals.

The Logging panel is the one dock with genuine behavior already: it
attaches a ``logging.Handler`` to the root logger so that every log
message the application emits (through
:func:`~src.core.logger.get_logger`, used throughout this codebase)
appears in this panel live, not just in the rotating file and console
output logger.py already provides.

Milestone 20 note: ``_QtLogHandler`` gained a real cross-thread-safety fix here, found by this
milestone's own tests (not a defect this milestone introduced -- the handler existed since
milestone 1b-ii, and readers already logged from worker threads before this milestone too; this
is simply the first call path that reliably crashed under test, and a crash found while adding
UI is a crash worth fixing on the same milestone that found it, not deferred). A ``logging.Handler``
whose ``emit()`` runs on whatever thread the logging call itself happens on -- and
:meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.run_stage`, called
from :class:`~src.ui.controllers.pipeline_controller.PipelineController` via
:class:`~src.ui.worker_runner.WorkerRunner`, logs from a ``QThreadPool`` worker thread -- was
calling ``QPlainTextEdit.appendPlainText`` directly from that non-GUI thread, which is undefined
behavior in Qt and reproduced as a real ``Windows fatal exception: access violation`` crash
during this milestone's own end-to-end test. The fix: ``_QtLogHandler`` is now also a ``QObject``
and routes the actual widget write through a ``Signal`` instead of calling the widget method
directly -- Qt's auto connection type resolves to a queued (thread-safe) delivery whenever the
emitting thread differs from the signal's own (GUI-thread) affinity, exactly the guarantee a
direct method call never had.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QDateTime, QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QPlainTextEdit,
    QTabWidget,
    QTreeWidgetItem,
)

from src.core.logger import get_logger
from src.ui.dataset_close_menu import DatasetCloseMenu
from src.ui.theme.tokens import DARK_TOKENS
from src.ui.widgets.chart_view import ChartView
from src.ui.widgets.chat_panel import ChatPanel
from src.ui.widgets.data_table.data_table_view import DataTableView
from src.ui.widgets.dataset_explorer_view import DatasetExplorerView

if TYPE_CHECKING:
    # A previous edit's ruff auto-fix pass stripped this import as
    # apparently-unused (the annotation-only reference on
    # self._theme_manager and attach_theme_manager's parameter, both
    # deferred strings under `from __future__ import annotations`, were
    # not visible to that pass) -- restored here since the type is genuinely
    # referenced twice below.
    from src.ui.theme_manager import ThemeManager

_logger = get_logger(__name__)


class _QtLogHandler(QObject, logging.Handler):
    """A ``logging.Handler`` that appends formatted records to a QPlainTextEdit.

    Kept as a private, module-level class rather than a method on
    :class:`DockManager` because ``logging.Handler`` has its own
    lifecycle (attached to and eventually removable from a logger)
    that is cleaner to reason about as a standalone object than as
    behavior mixed into the dock-construction class.

    Also a ``QObject`` (multiple inheritance alongside ``logging.Handler``) purely to own
    :attr:`_append_requested` -- see this module's own docstring for why a direct
    ``QPlainTextEdit.appendPlainText`` call from :meth:`emit` is not safe, and why the fix is
    "emit a signal instead of calling the widget," not e.g. a manual lock (a lock would only
    serialize the *write*, not move it onto the GUI thread Qt widgets actually require).
    """

    _append_requested = Signal(str)

    def __init__(self, text_widget: QPlainTextEdit) -> None:
        # Both base __init__s are called explicitly (super().__init__()
        # alone would only walk one branch of the MRO) -- QObject.__init__
        # sets up the signal/slot machinery this class needs;
        # logging.Handler.__init__ sets up the level/formatter/lock
        # attributes logging.Handler.handle() (called by the logging
        # module before emit()) assumes exist.
        QObject.__init__(self)
        logging.Handler.__init__(self)
        # AutoConnection (the default) resolves to Queued whenever the
        # emitting thread differs from this handler's own thread affinity
        # (the GUI thread, since it is constructed there -- see
        # DockManager._build_logging_dock) -- this is what makes a call to
        # emit() from a QThreadPool worker thread land safely back on the
        # GUI thread instead of touching text_widget cross-thread.
        self._append_requested.connect(text_widget.appendPlainText)

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        # mypy sees this as overriding QObject.emit (the low-level "emit an
        # arbitrary Qt signal by name" method PySide6 stubs for internal
        # use) rather than logging.Handler.emit, because this class
        # multiply-inherits both -- the two methods are unrelated in
        # practice (Python's MRO resolves the *call* through
        # logging.Handler.handle(), which is the only real caller), but
        # mypy compares signatures structurally against whichever base
        # declared it first. A genuine name collision from mixing two
        # unrelated base classes, not a real Liskov violation.
        try:
            message = self.format(record)
            self._append_requested.emit(message)
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
        # Set by attach_theme_manager() -- constructed after this class, by
        # src/core/app.py, the same reason main_window.py's own theme
        # manager reference is attached post-construction rather than
        # passed into __init__ (see MainWindow.attach_theme_manager's
        # docstring). None means "no theme applied yet"; display_chart()
        # falls back to DARK_TOKENS in that case rather than failing.
        self._theme_manager: ThemeManager | None = None

        # Milestone 18: dataset_id -> already-open DataTableView, so a
        # second double-click on the same dataset raises the existing tab
        # instead of opening a duplicate one. Populated by
        # display_dataset_table(); entries are dropped in
        # _on_data_table_tab_close_requested() when their tab closes.
        self._dataset_table_views: dict[str, DataTableView] = {}

        # Milestone 23: see connect_chart_closed below (dataset closing is handled by
        # DatasetCloseMenu itself -- constructed in _build_dataset_explorer_dock).
        self._chart_closed_handler: Callable[[str, str], None] | None = None

        self.dock_dataset_explorer = self._build_dataset_explorer_dock()
        self.dock_console = self._build_console_dock()
        self.dock_logging = self._build_logging_dock()
        self.dock_chart = self._build_chart_dock()
        self.dock_data_table = self._build_data_table_dock()
        self.dock_ai_chat = self._build_ai_chat_dock()

        parent_window.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_dataset_explorer
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
        # populated, not hidden behind a tab click the way Dataset
        # Explorer or Console/Log reasonably are.
        parent_window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.dock_chart
        )

        # Milestone 18: the data table dock IS tabbed with Chart -- unlike
        # the chart/AI-chat split above, a chart and a data table are the
        # same kind of thing (a view onto one dataset's content), so
        # sharing a tab strip rather than each claiming permanent screen
        # space matches how Console/Log are already tabbed for the same
        # reason.
        parent_window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.dock_data_table
        )
        parent_window.tabifyDockWidget(self.dock_chart, self.dock_data_table)

        # Milestone 10: the AI chat panel — stacked below the chart dock
        # in the same (right) area rather than tabbed with it, so a
        # chart and an in-progress conversation can both stay visible
        # at once (splitting vertically is Qt's default for two docks
        # added to the same area without an explicit tabifyDockWidget
        # call, matching how Console/Log are *deliberately* tabbed above
        # while this pair is not).
        parent_window.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.dock_ai_chat
        )
        parent_window.splitDockWidget(
            self.dock_chart, self.dock_ai_chat, Qt.Orientation.Vertical
        )

        # Milestone 20: Charts is demoted -- a chart's primary home is now
        # the Visualize stage page (milestone 24's own scope; the dock
        # itself is unaffected today), not the permanently-visible surface
        # it was before the workbench existed. The dock survives for
        # pinned side-by-side chart comparisons, it just no longer claims
        # screen space by default. See A3's dock-disposition table.
        self.dock_chart.hide()

        self.dock_dataset_explorer.raise_()
        self.dock_console.raise_()

        _logger.debug("Dock widgets constructed and attached to main window.")

    def _build_dataset_explorer_dock(self) -> QDockWidget:
        dock = QDockWidget("Dataset Explorer", self._parent_window)
        dock.setObjectName("dockDatasetExplorer")
        # Milestone 27: DatasetExplorerView owns the tree + EmptyState page switch -- see that
        # module's own docstring for why this was extracted out of DockManager. Stored as
        # self._dataset_explorer (not just a local variable) since refresh_dataset_list/
        # set_project_label below need to reach it after this constructor returns.
        self._dataset_explorer = DatasetExplorerView(dock)
        # Milestone 23: right-click "Close Dataset" -- see dataset_close_menu.py.
        self._dataset_close_menu = DatasetCloseMenu(self._dataset_explorer.tree)
        dock.setWidget(self._dataset_explorer)
        return dock

    def connect_dataset_close_requested(self, handler: Callable[[str], None]) -> None:
        """Call ``handler(dataset_id)`` when "Close Dataset" is chosen from the tree's context menu.

        See :mod:`~src.ui.dataset_close_menu`'s own docstring for the full rationale.
        """
        self._dataset_close_menu.connect(handler)

    def set_project_label(self, project_name: str | None) -> None:
        """Update the "Project" top-level node's text and rebuild the tree to show it.

        Milestone 20: the deleted Project Explorer dock's one job -- naming the open project
        (or "(No project open)") -- is absorbed as a top-level node in Dataset Explorer, per
        A3's dock-disposition table. Called by :mod:`src.ui.main_window` alongside
        :meth:`refresh_dataset_list`, from the same call sites that used to only update the
        status bar's project label (new/open/save-as).
        """
        self._dataset_explorer.set_project_label(project_name)

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

        Milestone 20: a top-level "Project" node (see :meth:`set_project_label`) is always the
        tree's first item now, ahead of either the dataset items below or (milestone 27) the
        :class:`~src.ui.widgets.empty_state.EmptyState` page -- the absorbed Project Explorer
        dock's one job, made visible here instead.

        Milestone 27: the actual tree-building/nesting logic (including the "(No datasets
        loaded)" -> ``EmptyState`` page switch) lives in
        :class:`~src.ui.widgets.dataset_explorer_view.DatasetExplorerView` -- see that class's
        own docstring for why it was extracted out of this method.
        """
        self._dataset_explorer.rebuild(datasets)

    def _build_console_dock(self) -> QDockWidget:
        dock = QDockWidget("Console", self._parent_window)
        dock.setObjectName("dockConsole")
        # Milestone 10: stored as self._console_text_widget (previously
        # a local variable, since nothing wrote to it after
        # construction) — append_console_message below needs to reach
        # it from outside __init__, the same reason
        # self._dataset_explorer and self._chart_tabs are retained.
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
        if widget is None:
            return
        # Milestone 23: forward display_chart(closable_ref=...)'s stashed property to
        # connect_chart_closed's handler -- None for a tab with no closable_ref.
        closable_ref = widget.property("closableRef")
        if closable_ref is not None and self._chart_closed_handler is not None:
            self._chart_closed_handler(*closable_ref)
        widget.deleteLater()  # removeTab() alone does not destroy the removed widget

    def connect_chart_closed(self, handler: Callable[[str, str], None]) -> None:
        """Call ``handler(kind, ref_id)`` when a chart-dock tab opened with a ``closable_ref``
        (see :meth:`display_chart`) is closed.

        Milestone 23: the same "genuinely reachable" close wiring
        :meth:`connect_dataset_close_requested` gives datasets, for visualizations and
        dashboards -- ``kind`` is ``"visualization"`` or ``"dashboard"``, matching whichever
        string :meth:`~src.ui.controllers.visualization_controller.VisualizationController.
        create_visualization`/``_on_dashboard_rendered`` passed as ``closable_ref``'s first
        element.
        """
        self._chart_closed_handler = handler

    def _build_data_table_dock(self) -> QDockWidget:
        dock = QDockWidget("Data Table", self._parent_window)
        dock.setObjectName("dockDataTable")
        # Milestone 18: mirrors _build_chart_dock's QTabWidget-of-
        # independent-views shape exactly -- one DataTableView per opened
        # dataset, each an independent tab, so viewing two datasets side
        # by side (via tab switching) works the same way comparing two
        # charts already does.
        self._data_table_tabs = QTabWidget(dock)
        self._data_table_tabs.setTabsClosable(True)
        self._data_table_tabs.tabCloseRequested.connect(
            self._on_data_table_tab_close_requested
        )
        dock.setWidget(self._data_table_tabs)
        return dock

    def _on_data_table_tab_close_requested(self, index: int) -> None:
        widget = self._data_table_tabs.widget(index)
        self._data_table_tabs.removeTab(index)
        if widget is None:
            return
        # Drop the dataset_id -> view entry for the tab that just closed,
        # so a later double-click on that dataset opens a fresh tab
        # instead of trying to re-show a widget removeTab() already
        # detached (indices would also be wrong here after a removal --
        # this is why display_dataset_table below looks views up by
        # dataset_id/widget identity, never by a stored tab index).
        stale_ids = [
            dataset_id
            for dataset_id, view in self._dataset_table_views.items()
            if view is widget
        ]
        for dataset_id in stale_ids:
            del self._dataset_table_views[dataset_id]
        widget.deleteLater()

    def connect_dataset_double_click(self, handler) -> None:
        """Call ``handler(dataset_id)`` when a Dataset Explorer entry is double-clicked.

        Milestone 18: before this, a dataset's tree item carried no
        machine-readable identity at all (only its display label) and
        nothing was connected to ``itemDoubleClicked`` -- double-clicking
        a dataset did nothing. ``refresh_dataset_list`` below now attaches
        each item's ``dataset_id`` via ``setData(0, Qt.ItemDataRole.
        UserRole, ...)``, which is what this reads back out.
        """

        def _on_item_double_clicked(item: QTreeWidgetItem, _column: int) -> None:
            dataset_id = item.data(0, Qt.ItemDataRole.UserRole)
            if dataset_id is not None:
                handler(dataset_id)

        self._dataset_explorer.tree.itemDoubleClicked.connect(_on_item_double_clicked)

    def display_dataset_table(self, dataset) -> None:
        """Open (or bring to front) a :class:`DataTableView` tab for ``dataset``.

        Args:
            dataset: A :class:`~src.services.workspace_service.Dataset`.
                Untyped here for the same reason ``refresh_dataset_list``'s
                ``datasets`` parameter is a plain ``list`` -- avoiding an
                import of ``src.services.workspace_service`` for one
                parameter's annotation alone.

        A dataset already open in its own tab is raised rather than
        duplicated -- double-clicking the same dataset twice should not
        accumulate identical tabs.
        """
        existing_view = self._dataset_table_views.get(dataset.dataset_id)
        if existing_view is not None:
            index = self._data_table_tabs.indexOf(existing_view)
            if index != -1:
                self._data_table_tabs.setCurrentIndex(index)
                self.dock_data_table.raise_()
                self.dock_data_table.show()
                return
            # The view object survived but its tab did not (should not
            # happen given the close-handler cleanup above, but falling
            # through to rebuild rather than raising here keeps this
            # method itself never able to leave the dock in a broken
            # state over a bookkeeping edge case).
            del self._dataset_table_views[dataset.dataset_id]

        view = DataTableView(self._data_table_tabs)
        view.load_dataset(dataset)
        index = self._data_table_tabs.addTab(view, dataset.name)
        self._dataset_table_views[dataset.dataset_id] = view
        self._data_table_tabs.setCurrentIndex(index)
        self.dock_data_table.raise_()
        self.dock_data_table.show()

    def display_chart(
        self,
        figure,
        name: str | None = None,
        closable_ref: tuple[str, str] | None = None,
    ) -> None:
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
            closable_ref: Milestone 23. ``(kind, id)`` -- ``("visualization",
                visualization_id)`` or ``("dashboard", dashboard_id)`` -- identifying which
                :class:`~src.services.workspace_service.WorkspaceService`-tracked object this
                tab represents, so :meth:`connect_chart_closed`'s handler can actually close
                it when the tab closes. ``None`` (the default) for a tab with nothing tracked
                to close (an AI-built chart -- milestone 9's ``build_chart`` tool -- is never
                added as a :class:`~src.services.workspace_service.Visualization`), matching
                every call site written before this milestone, which keeps working unchanged.
        """
        chart_view = ChartView(self._chart_tabs)
        tokens = (
            self._theme_manager.current_tokens()
            if self._theme_manager is not None
            else None
        ) or DARK_TOKENS
        chart_view.display_figure(figure, tokens)
        if closable_ref is not None:
            chart_view.setProperty("closableRef", closable_ref)
        tab_label = name or f"Chart {self._chart_tabs.count() + 1}"
        index = self._chart_tabs.addTab(chart_view, tab_label)
        self._chart_tabs.setCurrentIndex(index)
        self.dock_chart.raise_()
        self.dock_chart.show()

    def attach_theme_manager(self, theme_manager: ThemeManager) -> None:
        """Subscribe every open and future :class:`ChartView` to theme changes.

        Called once by :mod:`src.ui.main_window` from its own
        ``attach_theme_manager`` (mirroring how that method itself is
        called once by :mod:`src.core.app` after the ``QApplication``
        exists), so that a theme toggle recolours every chart tab already
        open at the time via ``Plotly.relayout`` -- no page reload, no
        flicker -- rather than only affecting charts opened after the
        toggle.
        """
        self._theme_manager = theme_manager
        theme_manager.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _theme_name: str) -> None:
        if self._theme_manager is None:
            return
        tokens = self._theme_manager.current_tokens()
        if tokens is None:
            return
        for index in range(self._chart_tabs.count()):
            widget = self._chart_tabs.widget(index)
            if isinstance(widget, ChartView):
                widget.apply_theme(tokens)

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
            self.dock_dataset_explorer.toggleViewAction(),
            self.dock_console.toggleViewAction(),
            self.dock_logging.toggleViewAction(),
            self.dock_chart.toggleViewAction(),
            self.dock_data_table.toggleViewAction(),
            self.dock_ai_chat.toggleViewAction(),
        ]
