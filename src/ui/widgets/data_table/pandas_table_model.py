# File: src/ui/widgets/data_table/pandas_table_model.py
"""A ``QAbstractTableModel`` over a ``pandas.DataFrame`` -- the dataframe viewer's core.

``QTableView`` is already virtualized: it calls ``data()`` only for cells
currently on screen, not once per row in the frame. The failure mode this
model has to avoid is never the *view* -- it is a model doing anything
O(n) per call, which would turn "already virtualized" into "virtualized on
top of an O(n) cell read," defeating the point.

**Rejected: ``QSortFilterProxyModel``.** Its ``filterAcceptsRow`` is a
Python callback invoked once per *source* row on every filter change, and
it maintains a full source<->proxy index mapping as a Qt-internal
structure. On a 1M-row frame, that is roughly 1M individual Python function
calls per keystroke in a filter box -- three to four orders of magnitude
slower than a single vectorised numpy/pandas operation, and it throws away
the entire reason this application's compute layer is pandas/numpy in the
first place (see CLAUDE.md's "the compute is already native" framing).
Sorting and filtering here are instead done with ``np.argsort`` and a
boolean mask via ``np.flatnonzero`` -- see :meth:`sort` and
:meth:`set_filter_mask`.

The frame is held **by reference, never copied**. ``__init__`` does not
call ``.copy()``, and nothing else in this class does either --
:attr:`dataframe` returns the identical object a caller passed in, which
matters both for memory (a 1M-row frame copy is a real, avoidable cost) and
for a filter/sort operation staying cheap (only an index array is
recomputed, not the underlying data).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from src.ui.widgets.data_table.column_formatters import (
    MISSING_ACCESSIBLE_TEXT,
    format_value,
    is_missing,
)

if TYPE_CHECKING:
    pass


def _stable_sort_indices(values: np.ndarray, descending: bool) -> np.ndarray:
    """Return an index permutation sorting ``values``, missing entries always last.

    Two real bugs a naive ``np.argsort(values)[::-1]`` (for descending)
    has: (1) on an ``object``-dtype column (any string column with a
    missing value in it), ``np.argsort`` raises ``TypeError`` -- Python's
    ``<`` has no ordering between ``str`` and ``None``/``float('nan')``.
    (2) even on a numeric column, where NaN silently sorts as
    greater-than-everything under ascending order, reversing the *whole*
    array for descending moves NaN to the *front* instead of leaving it
    last -- not what any spreadsheet-like tool does, and confusing since
    "missing" would then mean something different depending on sort
    direction. Isolating missing entries first and sorting only the rest
    avoids both: real values are always compared only against other real
    values, and missing entries stay appended at the end regardless of
    ``descending``.
    """
    positions = np.arange(len(values))
    missing_mask = pd.isna(values)
    real_positions = positions[~missing_mask]
    real_values = values[~missing_mask]

    order = np.argsort(real_values, kind="stable")
    if descending:
        order = order[::-1]

    return np.concatenate([real_positions[order], positions[missing_mask]])


class PandasTableModel(QAbstractTableModel):
    """Exposes one ``pandas.DataFrame`` to a ``QTableView``.

    Args:
        dataframe: The frame to display. Stored by reference (see the
            module docstring) -- the caller retains ownership and may
            continue to read it elsewhere; this model must never mutate it.
        parent: Optional owning ``QObject``.
    """

    def __init__(self, dataframe: pd.DataFrame, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._frame = dataframe
        # Cached once at construction (O(columns)), not recomputed per
        # call -- headerData() and columnCount() are both called
        # frequently by QTableView's own layout/paint cycle.
        self._column_names: list[str] = [str(c) for c in dataframe.columns]

        row_count = len(dataframe)
        # _base_indices: which source rows currently pass the filter (all
        # of them, initially). _visible: _base_indices further permuted
        # by the active sort, if any -- proxy row i displays source row
        # self._visible[i]. Both are plain numpy arrays of positions, not
        # a Qt-internal mapping structure, which is what keeps
        # set_filter_mask/sort cheap relative to QSortFilterProxyModel.
        self._base_indices = np.arange(row_count, dtype=np.int64)
        self._visible = self._base_indices
        self._sort_column: int | None = None
        self._sort_descending = False

    @property
    def dataframe(self) -> pd.DataFrame:
        """The wrapped frame -- the identical object passed to ``__init__``."""
        return self._frame

    def rowCount(
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        if parent.isValid():
            return 0
        return len(self._visible)

    def columnCount(
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        if parent.isValid():
            return 0
        return len(self._column_names)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if not index.isValid():
            return None
        source_row = int(self._visible[index.row()])
        column = index.column()

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            value = self._frame.iat[source_row, column]
            return format_value(value)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            value = self._frame.iat[source_row, column]
            if is_missing(value):
                return MISSING_ACCESSIBLE_TEXT
            return format_value(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            value = self._frame.iat[source_row, column]
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._column_names[section]
        # Vertical header: the *source* row number (1-based, matching how
        # spreadsheets label rows), not the proxy position -- so a sorted
        # or filtered view still tells the user which original row a
        # given line came from, rather than relabeling rows 1..N on every
        # sort/filter change.
        return str(int(self._visible[section]) + 1)

    def sort(
        self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder
    ) -> None:
        """Sort by ``column``, called automatically by ``QTableView`` header clicks.

        Uses ``np.argsort(kind="stable")`` on one column's values via
        ``.iloc[self._base_indices, column].to_numpy()`` -- a single
        vectorised operation over the currently-filtered rows, not a
        Python-level comparison per row. ``kind="stable"`` means a
        secondary sort (clicking a second column) does not scramble the
        relative order of rows that tie on the new column, matching users'
        expectations from spreadsheet software. See
        :func:`_stable_sort_indices` for why missing values are isolated
        before sorting rather than handed straight to ``np.argsort``.
        """
        if self.rowCount() == 0:
            self._sort_column = column
            self._sort_descending = order == Qt.SortOrder.DescendingOrder
            return

        self.layoutAboutToBeChanged.emit()
        values = self._frame.iloc[self._base_indices, column].to_numpy()
        descending = order == Qt.SortOrder.DescendingOrder
        order_indices = _stable_sort_indices(values, descending)
        self._visible = self._base_indices[order_indices]
        self._sort_column = column
        self._sort_descending = descending
        self.layoutChanged.emit()

    def set_filter_mask(self, mask: np.ndarray | None) -> None:
        """Restrict the visible rows to where ``mask`` is ``True``.

        Args:
            mask: A boolean array the length of the full (unfiltered)
                frame, or ``None`` to clear filtering and show every row.
                Converted to source-row positions via ``np.flatnonzero`` --
                a single vectorised call, not a per-row Python filter
                (see the module docstring's ``QSortFilterProxyModel``
                rejection).

        Re-applies the active sort column (if any) to the new filtered
        row set, so filtering does not silently discard a sort the user
        already set up.
        """
        self.beginResetModel()
        if mask is None:
            self._base_indices = np.arange(len(self._frame), dtype=np.int64)
        else:
            self._base_indices = np.flatnonzero(mask)

        if self._sort_column is not None and len(self._base_indices) > 0:
            values = self._frame.iloc[self._base_indices, self._sort_column].to_numpy()
            order_indices = _stable_sort_indices(values, self._sort_descending)
            self._visible = self._base_indices[order_indices]
        else:
            self._visible = self._base_indices
        self.endResetModel()

    def source_row_count(self) -> int:
        """The full, unfiltered row count -- distinct from :meth:`rowCount`."""
        return len(self._frame)
