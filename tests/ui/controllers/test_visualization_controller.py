# File: tests/ui/controllers/test_visualization_controller.py
"""Tests for VisualizationController.on_chart_closed -- milestone 23 acceptance criterion 3.

"close_visualization/close_dashboard are reachable from UI -- test that triggering the UI
action actually calls through to the WorkspaceService method with the right id." Connected to
:meth:`~src.ui.dock_manager.DockManager.connect_chart_closed`, fired when a chart-dock tab
opened with a ``closable_ref`` (see :meth:`~src.ui.dock_manager.DockManager.display_chart`) is
closed -- see :func:`test_create_visualization_wires_a_closable_ref_that_closes_it` for the
tab-close half of that path.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from PySide6.QtWidgets import QApplication, QMainWindow

from src.services.workspace_service import (
    Dashboard,
    DashboardTile,
    Dataset,
    Visualization,
    WorkspaceService,
)
from src.ui.controllers.visualization_controller import VisualizationController
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.worker_runner import WorkerRunner


def _make_controller(
    qapp: QApplication,
) -> tuple[VisualizationController, WorkspaceService, DockManager]:
    workspace_service = WorkspaceService()
    window = QMainWindow()
    dock_manager = DockManager(window)
    controller = VisualizationController(
        window,
        workspace_service,
        dock_manager,
        ApplicationStatusBar(window),
        UiStateBus(window),
        WorkerRunner(window),
    )
    return controller, workspace_service, dock_manager


def test_on_chart_closed_with_visualization_kind_calls_close_visualization(
    qapp: QApplication,
) -> None:
    controller, workspace_service, _dock_manager = _make_controller(qapp)
    dataset = Dataset(name="d", dataframe=pd.DataFrame({"a": [1]}), source_format="csv")
    workspace_service.add_dataset(dataset)
    visualization = Visualization(
        name="v", dataset_id=dataset.dataset_id, figure=go.Figure(), chart_type="bar"
    )
    workspace_service.add_visualization(visualization)

    controller.on_chart_closed("visualization", visualization.visualization_id)

    assert workspace_service.list_visualizations() == []


def test_on_chart_closed_with_dashboard_kind_calls_close_dashboard(
    qapp: QApplication,
) -> None:
    controller, workspace_service, _dock_manager = _make_controller(qapp)
    dataset = Dataset(name="d", dataframe=pd.DataFrame({"a": [1]}), source_format="csv")
    workspace_service.add_dataset(dataset)
    visualization = Visualization(
        name="v", dataset_id=dataset.dataset_id, figure=go.Figure(), chart_type="bar"
    )
    workspace_service.add_visualization(visualization)
    dashboard = Dashboard(
        name="dash",
        tiles=[
            DashboardTile(
                visualization_id=visualization.visualization_id, row=0, column=0
            )
        ],
    )
    workspace_service.add_dashboard(dashboard)

    controller.on_chart_closed("dashboard", dashboard.dashboard_id)

    assert workspace_service.list_dashboards() == []


def test_on_chart_closed_with_a_stale_id_does_not_raise(qapp: QApplication) -> None:
    controller, _workspace_service, _dock_manager = _make_controller(qapp)

    controller.on_chart_closed("visualization", "not-a-real-id")


def test_create_visualization_wires_a_closable_ref_that_closes_it(
    qapp: QApplication,
) -> None:
    """End-to-end reachability: create a visualization through the real controller path, close
    its chart-dock tab, and assert the workspace no longer tracks it -- the actual "close" UI
    action a user would trigger, not just the handler called directly.
    """
    controller, workspace_service, dock_manager = _make_controller(qapp)
    dataset = Dataset(
        name="d", dataframe=pd.DataFrame({"a": [1, 2]}), source_format="csv"
    )
    workspace_service.add_dataset(dataset)
    workspace_service.set_active_dataset(dataset.dataset_id)

    dock_manager.connect_chart_closed(controller.on_chart_closed)
    visualization = Visualization(
        name="v", dataset_id=dataset.dataset_id, figure=go.Figure(), chart_type="bar"
    )
    workspace_service.add_visualization(visualization)
    dock_manager.display_chart(
        go.Figure(),
        name="v",
        closable_ref=("visualization", visualization.visualization_id),
    )

    dock_manager._on_chart_tab_close_requested(0)  # the real tabCloseRequested handler

    assert workspace_service.list_visualizations() == []
