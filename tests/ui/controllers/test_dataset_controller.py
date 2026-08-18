# File: tests/ui/controllers/test_dataset_controller.py
"""Tests for DatasetController.close_dataset -- milestone 23 acceptance criterion 3.

"close_dataset/close_visualization/close_dashboard/delete_profile are reachable from UI --
test that triggering the UI action actually calls through to the WorkspaceService method with
the right id." :meth:`~src.ui.dataset_close_menu.DatasetCloseMenu` (tested directly in
``tests/ui/test_dataset_close_menu.py``) is what a real right-click drives; this file covers
the controller method that context menu is wired to in ``main_window.py``, against a real
:class:`~src.services.workspace_service.WorkspaceService`.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication, QMainWindow

from src.services.workspace_service import Dataset, WorkspaceService
from src.ui.controllers.dataset_controller import DatasetController
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.worker_runner import WorkerRunner


def _make_controller(qapp: QApplication) -> tuple[DatasetController, WorkspaceService]:
    workspace_service = WorkspaceService()
    window = QMainWindow()
    controller = DatasetController(
        window,
        workspace_service,
        DockManager(window),
        ApplicationStatusBar(window),
        UiStateBus(window),
        WorkerRunner(window),
    )
    return controller, workspace_service


def _make_dataset() -> Dataset:
    return Dataset(
        name="closeable", dataframe=pd.DataFrame({"a": [1, 2]}), source_format="csv"
    )


def test_close_dataset_calls_through_to_workspace_service_with_the_right_id(
    qapp: QApplication,
) -> None:
    controller, workspace_service = _make_controller(qapp)
    dataset = _make_dataset()
    workspace_service.add_dataset(dataset)
    workspace_service.set_active_dataset(dataset.dataset_id)

    controller.close_dataset(dataset.dataset_id)

    assert workspace_service.list_datasets() == []
    assert workspace_service.get_active_dataset() is None


def test_close_dataset_with_a_stale_id_does_not_raise(qapp: QApplication) -> None:
    controller, _workspace_service = _make_controller(qapp)

    controller.close_dataset(
        "not-a-real-id"
    )  # logged, not raised -- see close_dataset's docstring
