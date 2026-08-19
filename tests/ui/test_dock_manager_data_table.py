# File: tests/ui/test_dock_manager_data_table.py
"""Tests for DockManager's milestone-18 data-table dock and double-click wiring.

The M18 acceptance criterion this backs: "Double-clicking a dataset in the
explorer opens a table showing real cell values -- first time this has
ever been possible in the app."
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow

from src.services.workspace_service import Dataset
from src.ui.dock_manager import DockManager


def _make_dataset(name: str = "test") -> Dataset:
    frame = pd.DataFrame({"a": [1, 2, 3]})
    return Dataset(name=name, dataframe=frame, source_format="csv")


def test_dataset_tree_items_carry_their_dataset_id(qapp: QApplication) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    dataset = _make_dataset()
    manager.refresh_dataset_list([dataset])

    # Milestone 20: index 0 is now the absorbed "Project" node (see
    # DockManager.set_project_label) -- the dataset item is index 1.
    item = manager._dataset_explorer.tree.topLevelItem(1)
    assert item.data(0, Qt.ItemDataRole.UserRole) == dataset.dataset_id


def test_double_click_handler_receives_the_dataset_id(qapp: QApplication) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    dataset = _make_dataset()
    manager.refresh_dataset_list([dataset])

    received = []
    manager.connect_dataset_double_click(received.append)

    item = manager._dataset_explorer.tree.topLevelItem(1)
    manager._dataset_explorer.tree.itemDoubleClicked.emit(item, 0)

    assert received == [dataset.dataset_id]


def test_display_dataset_table_opens_a_tab_with_real_cell_values(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    dataset = _make_dataset()

    manager.display_dataset_table(dataset)

    assert manager._data_table_tabs.count() == 1
    view = manager._data_table_tabs.widget(0)
    assert view.model.rowCount() == 3
    assert view.model.data(view.model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "1"


def test_display_dataset_table_reuses_the_existing_tab_for_the_same_dataset(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    dataset = _make_dataset()

    manager.display_dataset_table(dataset)
    manager.display_dataset_table(dataset)  # double-clicked again

    assert manager._data_table_tabs.count() == 1  # not duplicated


def test_display_dataset_table_opens_separate_tabs_for_different_datasets(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)

    manager.display_dataset_table(_make_dataset("first"))
    manager.display_dataset_table(_make_dataset("second"))

    assert manager._data_table_tabs.count() == 2


def test_closing_a_tab_lets_a_later_double_click_reopen_it(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    dataset = _make_dataset()
    manager.display_dataset_table(dataset)

    manager._on_data_table_tab_close_requested(0)
    assert manager._data_table_tabs.count() == 0
    assert dataset.dataset_id not in manager._dataset_table_views

    manager.display_dataset_table(dataset)
    assert manager._data_table_tabs.count() == 1


def test_data_table_dock_has_a_toggle_view_action(qapp: QApplication) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    assert (
        manager.dock_data_table.toggleViewAction() in manager.view_menu_toggle_actions()
    )
