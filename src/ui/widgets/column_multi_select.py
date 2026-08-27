# File: src/ui/widgets/column_multi_select.py
"""A checkable multi-select list of dataset column names.

Milestone 24's own reason for existing: every column-picker in this codebase before this
milestone was a single-selection :class:`QComboBox` (:class:`~src.ui.dialogs.
create_visualization_dialog.CreateVisualizationDialog`'s per-field pickers,
:class:`~src.ui.dialogs.analysis_parameter_dialog.AnalysisParameterDialog`'s column fields),
which cannot represent a chart parameter that is a ``list[str]`` of columns (Treemap's
``path_columns``, Radar's ``value_columns``) or a "pick two or more columns to compare" workflow
(:class:`~src.ui.workbench.pages.visualize_page.VisualizePage`'s recommendation flow). Rather
than a comma-separated free-text field -- the workaround :class:`AnalysisParameterDialog`'s own
docstring names for its array-typed, non-column fields -- this is a real list widget: no typing
a column name correctly from memory, no risk of a typo silently producing an "unknown column"
error deep inside a chart's ``build()``.

Uses :class:`QListWidget` with ``Qt.ItemFlag.ItemIsUserCheckable`` items rather than
``QAbstractItemView.SelectionMode.MultiSelection`` -- extended/multi selection in Qt is a
*visual highlight* toggled by Ctrl/Shift-click or Ctrl+click, which is neither keyboard-discoverable
(no indication a control supports multi-select without already knowing the modifier) nor
screen-reader-legible (a highlighted row announces as "selected", indistinguishable from "focused").
A checkbox per row is both: Space toggles it with plain Tab navigation, and a checked/unchecked
state announces unambiguously through Qt's accessibility bridge.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QWidget

from src.ui.a11y.accessible import describe


class ColumnMultiSelect(QListWidget):
    """A checkable list of column names; checked items are the current selection.

    Signals:
        selection_changed: Emitted with the currently checked column names, in the
            order :meth:`set_columns` originally listed them (i.e. dataset column order,
            not check order) -- matching :class:`~src.visualization.chart_recommender.
            ChartSuggestion.columns`'s own "in the order the corresponding chart builder
            expects them" contract, so a caller that seeds a chart's ``path_columns``/
            ``value_columns`` from this widget's selection does not need to re-sort it.
    """

    selection_changed = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # No native selection highlight -- checkbox state is the only
        # selection signal this widget exposes (see module docstring).
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        describe(
            self,
            name="Columns",
            description="Check two or more columns to select them.",
        )
        self.itemChanged.connect(self._on_item_changed)

    def set_columns(self, column_names: list[str]) -> None:
        """Replace the list's contents with ``column_names``, all initially unchecked."""
        self.blockSignals(True)
        self.clear()
        for name in column_names:
            item = QListWidgetItem(name, self)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.addItem(item)
        self.blockSignals(False)

    def selected_columns(self) -> list[str]:
        """Return the checked column names, in the order :meth:`set_columns` listed them."""
        return [
            self.item(row).text()
            for row in range(self.count())
            if self.item(row).checkState() == Qt.CheckState.Checked
        ]

    def set_selected_columns(self, column_names: list[str]) -> None:
        """Check exactly the columns named in ``column_names``; uncheck every other row.

        Emits :attr:`selection_changed` once at the end rather than once per row --
        callers pre-filling a selection (e.g. from a
        :class:`~src.visualization.chart_recommender.ChartSuggestion`) want one
        notification of the final state, not one per intermediate checkbox toggle.
        """
        wanted = set(column_names)
        self.blockSignals(True)
        for row in range(self.count()):
            item = self.item(row)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.text() in wanted
                else Qt.CheckState.Unchecked
            )
        self.blockSignals(False)
        self.selection_changed.emit(self.selected_columns())

    def _on_item_changed(self, _item: QListWidgetItem) -> None:
        self.selection_changed.emit(self.selected_columns())
