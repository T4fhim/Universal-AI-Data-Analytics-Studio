# File: src/ui/controllers/visualization_controller.py
"""Owns visualization creation and combining visualizations into a dashboard.

Moved out of ``main_window.py`` in milestone 19 -- see
:mod:`src.ui.controllers`'s own docstring for why this package exists.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from src.core.exceptions import ApplicationError
from src.core.logger import get_logger
from src.services.workspace_service import (
    Dashboard,
    DashboardTile,
    Visualization,
    WorkspaceService,
)
from src.ui.dialogs.create_visualization_dialog import CreateVisualizationDialog
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.worker_runner import WorkerRunner
from src.visualization.dashboard_renderer import render_dashboard

_logger = get_logger(__name__)


class VisualizationController:
    """Handles creating a single visualization and combining several into a dashboard.

    Args:
        parent: The window dialogs should be parented to.
        workspace_service: Visualizations/dashboards are added and
            activated here.
        dock_manager: For opening chart tabs and appending console
            messages.
        status_bar: For busy/progress/message feedback.
        state_bus: Refreshed after a visualization is created, since
            ``visualization_count`` just changed.
        worker_runner: Runs dashboard rendering (a real, tile-count-scaling
            operation) off the UI thread.
    """

    def __init__(
        self,
        parent: QWidget,
        workspace_service: WorkspaceService,
        dock_manager: DockManager,
        status_bar: ApplicationStatusBar,
        state_bus: UiStateBus,
        worker_runner: WorkerRunner,
    ) -> None:
        self._parent = parent
        self._workspace_service = workspace_service
        self._dock_manager = dock_manager
        self._status_bar = status_bar
        self._state_bus = state_bus
        self._worker_runner = worker_runner

    def create_visualization(self) -> None:
        active_dataset = self._workspace_service.get_active_dataset()
        if active_dataset is None:
            QMessageBox.information(
                self._parent,
                "No Active Dataset",
                "Open or select a dataset before creating a visualization.",
            )
            return

        dialog = CreateVisualizationDialog(active_dataset.dataframe, self._parent)
        if dialog.exec() != CreateVisualizationDialog.DialogCode.Accepted:
            return

        figure, chart_type, parameters = dialog.get_result()
        visualization = self._register_visualization(
            active_dataset.dataset_id,
            active_dataset.name,
            figure,
            chart_type,
            parameters,
        )
        self._dock_manager.display_chart(
            figure,
            name=visualization.name,
            closable_ref=("visualization", visualization.visualization_id),
        )

    def register_built_visualization(
        self, figure: object, chart_type: str, parameters: dict
    ) -> None:
        """Register an already-built figure into the workspace -- milestone 24's
        :class:`~src.ui.workbench.pages.visualize_page.VisualizePage` builds its own figure
        inline (see that page's own docstring for why) rather than opening
        :class:`~src.ui.dialogs.create_visualization_dialog.CreateVisualizationDialog`, but
        the two paths otherwise need identical workspace bookkeeping -- create a
        :class:`~src.services.workspace_service.Visualization`, add it, set it active, and
        refresh dependent UI. This method is that shared tail, called with the dialog-built
        tuple's exact ``(figure, chart_type, parameters)`` shape so :meth:`create_visualization`
        and this method never drift into two different bookkeeping sequences.

        Unlike :meth:`create_visualization`, this does **not** call
        :meth:`~src.ui.dock_manager.DockManager.display_chart` -- ``VisualizePage`` already
        renders the figure inline in its own :class:`~src.ui.widgets.chart_view.ChartView`
        (see :meth:`~src.ui.dock_manager.DockManager.display_chart`'s own docstring on the
        Charts dock's demotion to secondary/default-hidden as of milestone 20), so opening a
        second chart dock tab for the same figure would be a redundant, unrequested extra
        window rather than genuinely new information.
        """
        active_dataset = self._workspace_service.get_active_dataset()
        if (
            active_dataset is None
        ):  # pragma: no cover -- defensive; VisualizePage requires
            # an active dataset before its build button is reachable at all (see
            # VisualizePage._on_build_clicked's own "No Active Dataset" guard), so this
            # path is not normally reachable, but a signal-connected slot must not assume
            # the state that produced its signal is still true by the time it runs.
            _logger.warning(
                "register_built_visualization called with no active dataset; dropped."
            )
            return
        self._register_visualization(
            active_dataset.dataset_id,
            active_dataset.name,
            figure,
            chart_type,
            parameters,
        )

    def _register_visualization(
        self,
        dataset_id: str,
        dataset_name: str,
        figure: object,
        chart_type: str,
        parameters: dict,
    ) -> Visualization:
        """Shared tail of :meth:`create_visualization`/:meth:`register_built_visualization`:
        build the :class:`~src.services.workspace_service.Visualization`, add it, activate
        it, and refresh dependent UI -- see :meth:`register_built_visualization`'s own
        docstring for why this exists as a separate method rather than being inlined into
        each caller."""
        visualization = Visualization(
            name=parameters.get("title") or f"{chart_type} of {dataset_name}",
            dataset_id=dataset_id,
            figure=figure,
            chart_type=chart_type,
            chart_parameters=parameters,
        )
        self._workspace_service.add_visualization(visualization)
        self._workspace_service.set_active_visualization(visualization.visualization_id)
        self._state_bus.request_refresh()  # visualization_count just changed

        self._status_bar.show_message(f"Created visualization: {visualization.name}")
        self._dock_manager.append_console_message(
            f"Created visualization '{visualization.name}' ({chart_type})."
        )
        _logger.info(
            "Visualization created via UI: %s (%s)", visualization.name, chart_type
        )
        return visualization

    def create_dashboard(self) -> None:
        """Combine every currently tracked visualization into one auto-arranged dashboard.

        A first, bounded version -- combines all visualizations rather than
        offering a picker/layout designer, which is real additional UI
        work not built yet. Grid arranged 2 columns wide, row-major order,
        matching how many tiles happen to exist.
        """
        visualizations = self._workspace_service.list_visualizations()
        if len(visualizations) < 2:
            QMessageBox.information(
                self._parent,
                "Not Enough Visualizations",
                "Create at least 2 visualizations before building a dashboard.",
            )
            return

        columns_per_row = 2
        tiles = [
            DashboardTile(
                visualization_id=viz.visualization_id,
                row=i // columns_per_row,
                column=i % columns_per_row,
            )
            for i, viz in enumerate(visualizations)
        ]
        dashboard = Dashboard(name="Dashboard", tiles=tiles)

        try:
            self._workspace_service.add_dashboard(dashboard)
            resolved = self._workspace_service.get_dashboard_tiles(
                dashboard.dashboard_id
            )
        except ApplicationError as exc:
            QMessageBox.critical(self._parent, "Failed to Create Dashboard", str(exc))
            _logger.warning("Dashboard creation failed: %s", exc)
            return

        # Milestone 6: render_dashboard's Plotly-figure assembly is a
        # named hot spot in the milestone plan (alongside dataset reads
        # and project reload) -- offloaded the same way, since combining
        # several figures into one grid is real work that scales with
        # tile count.
        self._status_bar.show_busy("Building dashboard…")
        self._worker_runner.run(
            render_dashboard,
            dashboard,
            resolved,
            on_result=lambda figure: self._on_dashboard_rendered(
                figure, len(tiles), dashboard.dashboard_id
            ),
            on_error=self._on_dashboard_render_error,
            on_progress=self._status_bar.show_progress,
            on_finished=self._status_bar.hide_busy,
        )

    def _on_dashboard_rendered(
        self, combined_figure, tile_count: int, dashboard_id: str
    ) -> None:
        self._dock_manager.display_chart(
            combined_figure, name="Dashboard", closable_ref=("dashboard", dashboard_id)
        )
        self._status_bar.show_message(
            f"Created dashboard with {tile_count} visualization(s)."
        )
        self._dock_manager.append_console_message(
            f"Created dashboard with {tile_count} visualization(s)."
        )
        _logger.info("Dashboard created via UI: %d tile(s).", tile_count)

    # -- Closing (milestone 23) --------------------------------------------------------

    def on_chart_closed(self, kind: str, ref_id: str) -> None:
        """Close whichever workspace object a just-closed chart-dock tab represented.

        Connected to :meth:`~src.ui.dock_manager.DockManager.connect_chart_closed`, which
        fires with the ``closable_ref`` a tab was opened with (see :meth:`create_visualization`/
        :meth:`_on_dashboard_rendered` above) -- ``kind`` is always either ``"visualization"``
        or ``"dashboard"`` (the only two kinds either call site ever passes), dispatched to the
        matching :class:`~src.services.workspace_service.WorkspaceService` close method. A tab
        opened with no ``closable_ref`` (an AI-built chart not tracked as a real
        :class:`~src.services.workspace_service.Visualization` -- see
        :meth:`~src.ui.dock_manager.DockManager.display_chart`'s own docstring) never reaches
        this method at all; that gap is not this milestone's scope.
        """
        try:
            if kind == "visualization":
                self._workspace_service.close_visualization(ref_id)
            elif kind == "dashboard":
                self._workspace_service.close_dashboard(ref_id)
            else:  # pragma: no cover -- defensive; only the two kinds above are ever passed
                _logger.warning("Unknown closable_ref kind: %r", kind)
                return
        except ApplicationError as exc:
            _logger.warning("Could not close %s %s: %s", kind, ref_id, exc)
            return
        self._state_bus.request_refresh()  # visualization_count just changed
        self._dock_manager.append_console_message(f"Closed {kind} {ref_id}.")
        _logger.info("Closed %s via UI: %s", kind, ref_id)

    def _on_dashboard_render_error(self, exc: Exception, traceback_text: str) -> None:
        _logger.error("Dashboard rendering failed: %s\n%s", exc, traceback_text)
        self._dock_manager.append_console_message(f"⚠ Dashboard creation failed: {exc}")
        QMessageBox.critical(self._parent, "Failed to Create Dashboard", str(exc))
