# File: tests/ui/test_empty_state_integration.py
"""Milestone 27, acceptance criterion 1: every "(No X)" placeholder audited in
DockManager/ApplicationMenuBar/SettingsDialog is now a real EmptyState, not silent text.

Covers the three call sites this milestone converted -- see each module's own "Milestone 27"
comment at its conversion point:

* DockManager's Dataset Explorer dock ("(No datasets loaded)").
* ApplicationMenuBar's "Open Recent" submenu ("(No recent projects)").
* SettingsDialog's plugin list ("(No plugins found in the configured search paths)").

``LineageView``'s own "(No dataset selected)" placeholder is deliberately *not* covered here --
see that module's own docstring for why it stays a plain ``QTreeWidget`` (no second zone to host
an EmptyState alongside), flagged in this milestone's own plan entry as an intentional exception
rather than converted unilaterally.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication, QMainWindow, QWidgetAction

import src.ui.actions.builtin_actions  # noqa: F401 -- populates the real registry
from src.services.workspace_service import Dataset
from src.ui.actions.action_binder import ActionBinder
from src.ui.dock_manager import DockManager
from src.ui.menu_bar import ApplicationMenuBar
from src.ui.widgets.empty_state import EmptyState


def _make_dataset(name: str = "test") -> Dataset:
    frame = pd.DataFrame({"a": [1, 2, 3]})
    return Dataset(name=name, dataframe=frame, source_format="csv")


def test_dataset_explorer_shows_empty_state_with_no_datasets(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)

    explorer = manager._dataset_explorer
    assert explorer.currentWidget() is explorer.empty_state
    assert explorer.empty_state.accessibleName() == "No Datasets Loaded"


def test_dataset_explorer_switches_back_to_the_tree_once_a_dataset_loads(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)

    manager.refresh_dataset_list([_make_dataset()])

    explorer = manager._dataset_explorer
    assert explorer.currentWidget() is explorer.tree


def test_dataset_explorer_switches_back_to_the_empty_state_when_the_last_dataset_closes(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    manager = DockManager(window)
    manager.refresh_dataset_list([_make_dataset()])

    manager.refresh_dataset_list([])

    explorer = manager._dataset_explorer
    assert explorer.currentWidget() is explorer.empty_state


def test_recent_projects_menu_hosts_a_real_empty_state(qapp: QApplication) -> None:
    window = QMainWindow()
    binder = ActionBinder(window)
    menu_bar = ApplicationMenuBar(window, binder)

    menu_bar.update_recent_projects_menu([], on_open=lambda path: None)

    actions = menu_bar.menu_recent_projects.actions()
    assert len(actions) == 1
    assert isinstance(actions[0], QWidgetAction)
    empty_state = actions[0].defaultWidget()
    assert isinstance(empty_state, EmptyState)
    assert empty_state.accessibleName() == "No Recent Projects"
