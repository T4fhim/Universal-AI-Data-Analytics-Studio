# File: tests/ui/test_dock_manager_workbench.py
"""Tests for DockManager's milestone-20 dock-disposition changes.

Backs the acceptance criterion: "Project Explorer dock is deleted; Dataset Explorer absorbs it
as a 'Project' node; Chart dock is demoted to default-hidden" -- the plan's only user-visible
removals in this milestone.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMainWindow

from src.ui.dock_manager import DockManager


def test_project_explorer_dock_no_longer_exists(qapp: QApplication) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    assert not hasattr(manager, "dock_project_explorer")


def test_dataset_explorer_shows_a_project_node_by_default(qapp: QApplication) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    top_item = manager._dataset_explorer.tree.topLevelItem(0)
    assert top_item.text(0) == "(No project open)"


def test_set_project_label_updates_the_absorbed_project_node(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)

    manager.set_project_label("My Analysis")

    top_item = manager._dataset_explorer.tree.topLevelItem(0)
    assert top_item.text(0) == "Project: My Analysis"


def test_set_project_label_preserves_already_loaded_datasets(
    qapp: QApplication,
) -> None:
    import pandas as pd

    from src.services.workspace_service import Dataset

    window = QMainWindow()
    manager = DockManager(window)
    dataset = Dataset(
        name="d1", dataframe=pd.DataFrame({"a": [1]}), source_format="csv"
    )
    manager.refresh_dataset_list([dataset])

    manager.set_project_label("My Analysis")

    # Project node at 0, the dataset still at 1 -- rebuilding to show the
    # new project label must not drop the dataset list.
    assert (
        manager._dataset_explorer.tree.topLevelItem(0).text(0) == "Project: My Analysis"
    )
    assert manager._dataset_explorer.tree.topLevelItemCount() == 2


def test_chart_dock_starts_hidden(qapp: QApplication) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    assert manager.dock_chart.isHidden()


def test_view_menu_toggle_actions_no_longer_include_project_explorer(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    labels = [action.text() for action in manager.view_menu_toggle_actions()]
    assert "Project Explorer" not in labels
    assert "Dataset Explorer" in labels
