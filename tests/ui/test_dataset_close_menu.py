# File: tests/ui/test_dataset_close_menu.py
"""Tests for DatasetCloseMenu -- the Dataset Explorer's right-click "Close Dataset" wiring.

``QMenu.exec`` opens a real, blocking, modal popup even offscreen -- there is nobody to dismiss
it in a headless test run, so every test here monkeypatches the instance's own ``_show_menu``
(the one method that calls ``exec``) to call the connected handler directly instead, the same
"intercept the blocking call, assert on what would have happened" approach
``tests/ui/conftest.py``'s own ``block_modals`` fixture uses for ``QMessageBox``. This still
exercises the real item-lookup/id-resolution path in ``_on_context_menu`` -- only the popup
itself is bypassed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidget, QTreeWidgetItem

from src.ui.dataset_close_menu import DatasetCloseMenu


def _bypass_the_popup(close_menu: DatasetCloseMenu) -> None:
    close_menu._show_menu = lambda dataset_id, _global_position: (  # type: ignore[method-assign]
        close_menu._handler(dataset_id)
    )


def test_right_clicking_a_dataset_item_calls_the_connected_handler_with_its_id(
    qapp: QApplication,
) -> None:
    tree = QTreeWidget()
    item = QTreeWidgetItem(tree, ["some-dataset (3 rows x 2 cols)"])
    item.setData(0, Qt.ItemDataRole.UserRole, "dataset-123")
    close_menu = DatasetCloseMenu(tree)
    _bypass_the_popup(close_menu)

    received: list[str] = []
    close_menu.connect(received.append)

    close_menu._on_context_menu(tree.visualItemRect(item).center())

    assert received == ["dataset-123"]


def test_right_clicking_empty_space_does_nothing(qapp: QApplication) -> None:
    tree = QTreeWidget()
    close_menu = DatasetCloseMenu(tree)
    _bypass_the_popup(close_menu)
    received: list[str] = []
    close_menu.connect(received.append)

    close_menu._on_context_menu(
        tree.rect().center()
    )  # no items at all -- itemAt() is None

    assert received == []


def test_right_clicking_with_nothing_connected_does_not_raise(
    qapp: QApplication,
) -> None:
    tree = QTreeWidget()
    item = QTreeWidgetItem(tree, ["some-dataset"])
    item.setData(0, Qt.ItemDataRole.UserRole, "dataset-123")
    close_menu = DatasetCloseMenu(tree)

    close_menu._on_context_menu(
        tree.visualItemRect(item).center()
    )  # no connect() call at all


def test_the_placeholder_project_item_carries_no_id_and_is_ignored(
    qapp: QApplication,
) -> None:
    """The "Project" / "(No datasets loaded)" items DockManager builds carry no UserRole
    data -- right-clicking them must not call the handler with ``None``."""
    tree = QTreeWidget()
    placeholder = QTreeWidgetItem(
        tree, ["Project: Demo"]
    )  # no setData call, unlike a dataset
    close_menu = DatasetCloseMenu(tree)
    _bypass_the_popup(close_menu)
    received: list[str] = []
    close_menu.connect(received.append)

    close_menu._on_context_menu(tree.visualItemRect(placeholder).center())

    assert received == []
