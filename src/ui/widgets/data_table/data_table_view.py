# File: src/ui/widgets/data_table/data_table_view.py
"""The dataframe viewer widget: filter bar + sort controls + a QTableView.

Composes :class:`~src.ui.widgets.data_table.pandas_table_model.PandasTableModel`
into a real, keyboard-operable table -- see that module's docstring for why
sorting/filtering are vectorised numpy/pandas operations rather than a
``QSortFilterProxyModel``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.core.logger import get_logger
from src.ui.a11y.accessible import describe
from src.ui.widgets.data_table.filter_bar import FilterBar
from src.ui.widgets.data_table.pandas_table_model import PandasTableModel
from src.workers import BaseWorker

if TYPE_CHECKING:
    import pandas as pd

    from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

# Above this row count, filter-mask computation moves off the UI thread.
# 200k is the plan's own figure -- large enough that a synchronous
# str-contains scan across every column is still comfortably sub-frame for
# anything smaller, small enough that a 1M-row frame's ~1s+ scan never
# blocks the UI thread even once.
_WORKER_FILTER_THRESHOLD_ROWS = 200_000

# resizeColumnsToContents() (Qt's own) scans every row for every column --
# O(rows x columns) calls into the model. Sampling the first N rows keeps
# column auto-sizing bounded regardless of frame size.
_COLUMN_WIDTH_SAMPLE_ROWS = 200
_MAX_COLUMN_WIDTH_PX = 400
_COLUMN_WIDTH_PADDING_PX = 24

# A column chooser only appears above this width -- most datasets never
# approach it, so building/showing the control unconditionally would be
# UI clutter for the common case.
_COLUMN_CHOOSER_THRESHOLD_COLUMNS = 1000


def _compute_filter_mask(frame: pd.DataFrame, needle: str) -> np.ndarray:
    """Return a boolean mask: rows where any column contains ``needle``.

    Module-level and touches no Qt/widget state, deliberately -- this is
    exactly what gets handed to :class:`~src.workers.base_worker.BaseWorker`
    for the above-:data:`_WORKER_FILTER_THRESHOLD_ROWS` path, mirroring
    ``main_window.py``'s own ``_read_recorded_datasets`` pattern (a
    module-level function a worker thread runs, with no UI-thread
    reference reachable from inside it).

    Vectorised per column (``Series.str.contains``, not a per-row Python
    loop) -- see ``pandas_table_model.py``'s module docstring for why a
    per-row callback is the exact failure mode this whole package avoids.
    """
    row_count = len(frame)
    if not needle:
        return np.ones(row_count, dtype=bool)

    lowered = needle.lower()
    mask = np.zeros(row_count, dtype=bool)
    for column in frame.columns:
        column_mask = (
            frame[column]
            .astype(str)
            .str.lower()
            .str.contains(lowered, regex=False, na=False)
            .to_numpy()
        )
        mask |= column_mask
    return mask


class DataTableView(QWidget):
    """Filter bar + sort controls + a virtualized table over one dataset."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model: PandasTableModel | None = None
        self._dataset_id: str | None = None
        self._active_filter_worker: BaseWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        self._filter_bar = FilterBar(self)
        self._filter_bar.filter_changed.connect(self._on_filter_changed)
        controls.addWidget(self._filter_bar, stretch=1)

        # A second, fully keyboard-operable path to sorting alongside the
        # header's native mouse-click sort: QHeaderView sections are
        # painted, not real child widgets, so Qt gives them no default
        # keyboard-activation behavior on their own. A QComboBox + toggle
        # QToolButton are both natively Tab-reachable and
        # Enter/Space-activatable, which is what the plan's "keyboard
        # sort... reachable via Tab" acceptance criterion actually needs.
        self._sort_column_combo = QComboBox(self)
        describe(
            self._sort_column_combo,
            name="Sort by column",
            description="Choose which column to sort the table by",
        )
        self._sort_column_combo.currentIndexChanged.connect(self._on_sort_changed)
        controls.addWidget(self._sort_column_combo)

        self._sort_descending_button = QToolButton(self)
        self._sort_descending_button.setCheckable(True)
        self._sort_descending_button.setText(self.tr("↓"))
        describe(
            self._sort_descending_button,
            name="Sort descending",
            description="Toggle between ascending and descending sort order",
        )
        self._sort_descending_button.toggled.connect(self._on_sort_changed)
        controls.addWidget(self._sort_descending_button)

        self._column_chooser_button = QPushButton("Columns…", self)
        self._column_chooser_button.clicked.connect(self._show_column_chooser)
        self._column_chooser_button.setVisible(False)
        controls.addWidget(self._column_chooser_button)

        layout.addLayout(controls)

        self._table_view = QTableView(self)
        self._table_view.setSortingEnabled(True)
        # Fixed row height: without this, Qt measures every row's ideal
        # height to compute the scrollbar's range, which is an O(rows)
        # pass at construction/resize time -- exactly the kind of
        # per-model-cell cost pandas_table_model.py's docstring says a
        # virtualized view must not reintroduce.
        self._table_view.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )
        self._table_view.verticalHeader().setDefaultSectionSize(24)
        self._table_view.setAlternatingRowColors(True)
        layout.addWidget(self._table_view)

        describe(
            self._table_view,
            name="Dataset table",
            description="The active dataset's rows and columns",
        )

    def load_dataset(self, dataset: Dataset) -> None:
        """Display ``dataset``, replacing any previously loaded one."""
        self._dataset_id = dataset.dataset_id
        self._model = PandasTableModel(dataset.dataframe, parent=self)
        self._table_view.setModel(self._model)

        self._filter_bar.clear()
        self._populate_sort_column_combo()
        self._resize_columns_sampled()
        self._update_column_chooser_visibility()

        describe(
            self._table_view,
            name=f"{dataset.name} data table",
            description=(f"{dataset.row_count} rows by {dataset.column_count} columns"),
        )

    def filter_by_text(self, text: str) -> None:
        """Programmatically apply ``text`` to the filter bar -- the paired-chart hook.

        Milestone 24's :class:`~src.ui.workbench.pages.visualize_page.VisualizePage`
        connects a :class:`~src.ui.widgets.chart_view.ChartView`'s
        :attr:`~src.ui.web.chart_bridge.ChartBridge.point_clicked` to this method, using
        the clicked point's category/x label as the filter text -- reusing this widget's
        existing whole-row substring filter (:class:`~src.ui.widgets.data_table.
        filter_bar.FilterBar`) rather than building a column-aware exact-match filter
        just for chart clicks, since the filter bar's own docstring already establishes
        substring/case-insensitive matching as this table's one filtering contract.
        """
        self._filter_bar.set_text(text)

    @property
    def dataset_id(self) -> str | None:
        return self._dataset_id

    @property
    def model(self) -> PandasTableModel | None:
        return self._model

    # -- Sorting ---------------------------------------------------------

    def _populate_sort_column_combo(self) -> None:
        self._sort_column_combo.blockSignals(True)
        self._sort_column_combo.clear()
        if self._model is not None:
            for column in range(self._model.columnCount()):
                self._sort_column_combo.addItem(
                    str(self._model.headerData(column, Qt.Orientation.Horizontal))
                )
        self._sort_column_combo.blockSignals(False)

    def _on_sort_changed(self, *_args) -> None:
        if self._model is None:
            return
        column = self._sort_column_combo.currentIndex()
        if column < 0:
            return
        order = (
            Qt.SortOrder.DescendingOrder
            if self._sort_descending_button.isChecked()
            else Qt.SortOrder.AscendingOrder
        )
        self._table_view.sortByColumn(column, order)

    # -- Filtering ---------------------------------------------------------

    def _on_filter_changed(self, text: str) -> None:
        if self._model is None:
            return
        frame = self._model.dataframe
        if len(frame) > _WORKER_FILTER_THRESHOLD_ROWS:
            self._filter_in_background(frame, text)
        else:
            mask = _compute_filter_mask(frame, text)
            self._model.set_filter_mask(mask)

    def _filter_in_background(self, frame: pd.DataFrame, text: str) -> None:
        """Compute the filter mask off the UI thread for a large frame.

        Returns immediately -- the mask is applied later, from
        :meth:`_on_filter_worker_result`, once the worker finishes. This
        is the acceptance-criterion behavior: the caller's own filter call
        does not block waiting for a 1M-row scan.
        """
        worker = BaseWorker(_compute_filter_mask, frame, text)
        worker.signals.result.connect(self._on_filter_worker_result)
        worker.signals.error.connect(self._on_filter_worker_error)
        self._active_filter_worker = worker
        QThreadPool.globalInstance().start(worker)

    def _on_filter_worker_result(self, mask: np.ndarray) -> None:
        self._active_filter_worker = None
        if self._model is not None:
            self._model.set_filter_mask(mask)

    def _on_filter_worker_error(self, exc: Exception, traceback_text: str) -> None:
        self._active_filter_worker = None
        _logger.error("Background dataset filter failed: %s\n%s", exc, traceback_text)

    # -- Layout helpers ---------------------------------------------------------

    def _resize_columns_sampled(self) -> None:
        """Auto-size columns from a bounded row sample, not the whole frame.

        ``QTableView.resizeColumnsToContents()`` (Qt's own) would call
        ``data()`` for every row of every column to compute an ideal
        width -- fine at a few thousand rows, a real stall at a million.
        This samples the first :data:`_COLUMN_WIDTH_SAMPLE_ROWS` only.
        """
        if self._model is None:
            return
        font_metrics = self._table_view.fontMetrics()
        sample_rows = min(_COLUMN_WIDTH_SAMPLE_ROWS, self._model.rowCount())

        for column in range(self._model.columnCount()):
            header_text = str(
                self._model.headerData(column, Qt.Orientation.Horizontal) or ""
            )
            max_width = font_metrics.horizontalAdvance(header_text)
            for row in range(sample_rows):
                index = self._model.index(row, column)
                text = str(self._model.data(index, Qt.ItemDataRole.DisplayRole) or "")
                max_width = max(max_width, font_metrics.horizontalAdvance(text))
            width = min(max_width + _COLUMN_WIDTH_PADDING_PX, _MAX_COLUMN_WIDTH_PX)
            self._table_view.setColumnWidth(column, width)

    # -- Column chooser (>1000 columns) ---------------------------------------

    def _update_column_chooser_visibility(self) -> None:
        column_count = self._model.columnCount() if self._model is not None else 0
        self._column_chooser_button.setVisible(
            column_count > _COLUMN_CHOOSER_THRESHOLD_COLUMNS
        )

    def _show_column_chooser(self) -> None:
        if self._model is None:
            return
        menu = QMenu(self)
        for column in range(self._model.columnCount()):
            name = str(self._model.headerData(column, Qt.Orientation.Horizontal))
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(not self._table_view.isColumnHidden(column))
            action.toggled.connect(
                lambda checked, col=column: self._table_view.setColumnHidden(
                    col, not checked
                )
            )
        menu.exec(
            self._column_chooser_button.mapToGlobal(
                self._column_chooser_button.rect().bottomLeft()
            )
        )
