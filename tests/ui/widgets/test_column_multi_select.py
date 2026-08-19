# File: tests/ui/widgets/test_column_multi_select.py
"""Tests for src.ui.widgets.column_multi_select.ColumnMultiSelect."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.widgets.column_multi_select import ColumnMultiSelect


def test_set_columns_populates_rows_all_unchecked(qapp: QApplication) -> None:
    widget = ColumnMultiSelect()
    widget.set_columns(["a", "b", "c"])

    assert widget.count() == 3
    assert widget.selected_columns() == []


def test_checking_two_items_returns_them_in_dataset_order(qapp: QApplication) -> None:
    widget = ColumnMultiSelect()
    widget.set_columns(["a", "b", "c"])

    # Check "c" first, then "a" -- selected_columns() must still return dataset
    # order (a, c), not check order (c, a).
    widget.item(2).setCheckState(Qt.CheckState.Checked)
    widget.item(0).setCheckState(Qt.CheckState.Checked)

    assert widget.selected_columns() == ["a", "c"]


def test_checking_an_item_emits_selection_changed(qapp: QApplication) -> None:
    widget = ColumnMultiSelect()
    widget.set_columns(["a", "b"])
    received: list[list[str]] = []
    widget.selection_changed.connect(received.append)

    widget.item(0).setCheckState(Qt.CheckState.Checked)

    assert received == [["a"]]


def test_set_selected_columns_checks_exactly_those_columns(qapp: QApplication) -> None:
    widget = ColumnMultiSelect()
    widget.set_columns(["a", "b", "c"])
    widget.item(0).setCheckState(Qt.CheckState.Checked)  # pre-existing selection

    widget.set_selected_columns(["b", "c"])

    assert widget.selected_columns() == ["b", "c"]


def test_set_selected_columns_emits_selection_changed_once(qapp: QApplication) -> None:
    widget = ColumnMultiSelect()
    widget.set_columns(["a", "b", "c"])
    received: list[list[str]] = []
    widget.selection_changed.connect(received.append)

    widget.set_selected_columns(["a", "b"])

    assert received == [["a", "b"]]


def test_set_columns_clears_previous_contents(qapp: QApplication) -> None:
    widget = ColumnMultiSelect()
    widget.set_columns(["a", "b"])
    widget.item(0).setCheckState(Qt.CheckState.Checked)

    widget.set_columns(["x", "y", "z"])

    assert widget.count() == 3
    assert widget.selected_columns() == []
