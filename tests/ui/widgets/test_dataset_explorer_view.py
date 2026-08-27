# File: tests/ui/widgets/test_dataset_explorer_view.py
"""Tests for DatasetExplorerView -- milestone 27's DockManager extraction.

Covers the same behaviors tests/ui/test_dock_manager_workbench.py and
tests/ui/test_dock_manager_data_table.py already verify through DockManager -- this file tests
the extracted widget directly, since a future DockManager caller could reuse it independently
of the dock chrome.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication

from src.services.workspace_service import Dataset
from src.ui.widgets.dataset_explorer_view import DatasetExplorerView


def _make_dataset(name: str = "test", parent_dataset_id: str | None = None) -> Dataset:
    frame = pd.DataFrame({"a": [1, 2, 3]})
    return Dataset(
        name=name,
        dataframe=frame,
        source_format="csv",
        parent_dataset_id=parent_dataset_id,
    )


def test_starts_on_the_empty_state_page_with_a_project_node_in_the_tree(
    qapp: QApplication,
) -> None:
    view = DatasetExplorerView()
    assert view.currentWidget() is view.empty_state
    assert view.tree.topLevelItem(0).text(0) == "(No project open)"


def test_set_project_label_updates_the_tree_node_without_changing_the_page(
    qapp: QApplication,
) -> None:
    view = DatasetExplorerView()

    view.set_project_label("My Analysis")

    assert view.tree.topLevelItem(0).text(0) == "Project: My Analysis"
    assert view.currentWidget() is view.empty_state


def test_rebuild_with_datasets_switches_to_the_tree_page(qapp: QApplication) -> None:
    view = DatasetExplorerView()
    dataset = _make_dataset()

    view.rebuild([dataset])

    assert view.currentWidget() is view.tree
    assert view.tree.topLevelItemCount() == 2  # Project node + the dataset
    item = view.tree.topLevelItem(1)
    assert dataset.name in item.text(0)


def test_rebuild_nests_a_derived_dataset_under_its_parent(qapp: QApplication) -> None:
    view = DatasetExplorerView()
    parent = _make_dataset("parent")
    child = _make_dataset("child", parent_dataset_id=parent.dataset_id)

    view.rebuild([parent, child])

    parent_item = view.tree.topLevelItem(1)
    assert parent_item.childCount() == 1
    assert child.name in parent_item.child(0).text(0)


def test_rebuild_back_to_empty_switches_back_to_the_empty_state_page(
    qapp: QApplication,
) -> None:
    view = DatasetExplorerView()
    view.rebuild([_make_dataset()])

    view.rebuild([])

    assert view.currentWidget() is view.empty_state
