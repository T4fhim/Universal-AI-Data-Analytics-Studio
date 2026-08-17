# File: tests/ui/widgets/data_table/test_data_table_view.py
"""Tests for DataTableView: loading, sorting, and the filter-worker threshold.

The M18 acceptance criterion this file backs directly: "Filtering above
~200k rows routes through WorkerRunner [BaseWorker in this codebase's
current infrastructure -- see the module docstring's own note], not the
UI thread -- a test asserts the UI thread's own filter call returns
immediately."
"""

from __future__ import annotations

import pandas as pd
import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from src.services.workspace_service import Dataset
from src.ui.widgets.data_table import data_table_view as data_table_view_module
from src.ui.widgets.data_table.data_table_view import DataTableView


class _RecordingThreadPool:
    """A stand-in for QThreadPool that records started workers without
    running them -- lets a test assert "a worker was offloaded" and "the
    model was not touched yet" in the same assertion, which a real thread
    pool (asynchronous, racing the test) could not give a deterministic
    answer to.
    """

    def __init__(self) -> None:
        self.started_workers: list = []

    def start(self, worker) -> None:
        self.started_workers.append(worker)


def _make_dataset(row_count: int) -> Dataset:
    frame = pd.DataFrame({"name": [f"row-{i}" for i in range(row_count)]})
    return Dataset(name="test", dataframe=frame, source_format="csv")


def test_load_dataset_populates_the_model(qapp: QApplication) -> None:
    view = DataTableView()
    dataset = _make_dataset(5)
    view.load_dataset(dataset)
    assert view.model is not None
    assert view.model.rowCount() == 5
    assert view.dataset_id == dataset.dataset_id


def test_load_dataset_clears_any_previous_filter_text(qapp: QApplication) -> None:
    view = DataTableView()
    view.load_dataset(_make_dataset(5))
    view._filter_bar._search.setText("row-1")
    view.load_dataset(_make_dataset(3))
    assert view._filter_bar.text() == ""


def test_sort_column_combo_is_populated_from_the_loaded_dataset(
    qapp: QApplication,
) -> None:
    view = DataTableView()
    frame = pd.DataFrame({"alpha": [1, 2], "beta": [3, 4]})
    view.load_dataset(Dataset(name="t", dataframe=frame, source_format="csv"))
    items = [
        view._sort_column_combo.itemText(i)
        for i in range(view._sort_column_combo.count())
    ]
    assert items == ["alpha", "beta"]


def test_below_threshold_filter_computes_synchronously(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Small frames never touch QThreadPool at all -- filtering happens
    directly on the UI thread, and the model updates immediately.
    """
    pool = _RecordingThreadPool()
    monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: pool))

    view = DataTableView()
    view.load_dataset(_make_dataset(10))

    view._filter_bar._search.setText("row-1")

    assert pool.started_workers == []  # no worker offloaded
    assert view.model.rowCount() == 1  # "row-1" is the only match


def test_above_threshold_filter_offloads_to_a_worker_and_returns_immediately(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance-criterion test itself: above the row-count
    threshold, the UI-thread call must return without having computed (or
    waited for) the filter result -- proven here by using a thread pool
    stand-in that records the worker but deliberately never runs it, then
    asserting the model's row count is *still the full, unfiltered count*
    immediately after the call returns.
    """
    monkeypatch.setattr(data_table_view_module, "_WORKER_FILTER_THRESHOLD_ROWS", 5)
    pool = _RecordingThreadPool()
    monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: pool))

    view = DataTableView()
    view.load_dataset(_make_dataset(10))  # 10 > the patched threshold of 5

    view._filter_bar._search.setText("row-1")

    assert len(pool.started_workers) == 1  # a worker WAS offloaded
    # The UI thread's own call returned without blocking on the (never
    # actually run, in this test) worker -- the model still shows every
    # row, not the filtered result, proving no synchronous computation
    # happened on this thread.
    assert view.model.rowCount() == 10


def test_worker_result_applies_the_filter_once_it_completes(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the above-threshold path: once the worker's
    result signal fires, the mask IS applied -- offloading is not simply
    dropping the filter request.
    """
    monkeypatch.setattr(data_table_view_module, "_WORKER_FILTER_THRESHOLD_ROWS", 5)
    view = DataTableView()
    view.load_dataset(_make_dataset(10))

    # Compute the "real" answer directly and feed it through the same
    # slot the worker's signals.result would call -- exercises the
    # apply-path without depending on QThreadPool's actual scheduling
    # timing inside a test.
    mask = data_table_view_module._compute_filter_mask(view.model.dataframe, "row-1")
    view._on_filter_worker_result(mask)

    assert view.model.rowCount() == 1


def test_compute_filter_mask_matches_any_column(qapp: QApplication) -> None:
    frame = pd.DataFrame({"a": ["foo", "bar"], "b": ["baz", "qux"]})
    mask = data_table_view_module._compute_filter_mask(frame, "qux")
    assert mask.tolist() == [False, True]


def test_compute_filter_mask_empty_needle_matches_everything(
    qapp: QApplication,
) -> None:
    frame = pd.DataFrame({"a": ["foo", "bar"]})
    mask = data_table_view_module._compute_filter_mask(frame, "")
    assert mask.tolist() == [True, True]


# -- Accessibility (M18's explicit acceptance criterion) ----------------


def test_table_has_a_real_accessible_name(qapp: QApplication) -> None:
    view = DataTableView()
    assert view._table_view.accessibleName() == "Dataset table"
    view.load_dataset(_make_dataset(3))
    assert "test" in view._table_view.accessibleName()


def test_filter_and_sort_controls_are_keyboard_reachable(qapp: QApplication) -> None:
    """The M18 acceptance criterion this backs: "keyboard sort/filter is
    reachable via Tab." QHeaderView sections have no default keyboard
    activation (see DataTableView's own module comment), so the sort
    combo/button pair is the actual reachable control checked here,
    alongside the filter box.
    """
    from PySide6.QtCore import Qt as QtCore_Qt

    view = DataTableView()
    for widget in (
        view._filter_bar._search,
        view._sort_column_combo,
        view._sort_descending_button,
    ):
        assert widget.focusPolicy() != QtCore_Qt.FocusPolicy.NoFocus
