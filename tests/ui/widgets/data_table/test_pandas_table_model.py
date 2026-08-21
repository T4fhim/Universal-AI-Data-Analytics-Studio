# File: tests/ui/widgets/data_table/test_pandas_table_model.py
"""Correctness and performance tests for PandasTableModel.

Needs a real QApplication (QAbstractTableModel requires one) -- the qapp
fixture from tests/ui/conftest.py.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.widgets.data_table.column_formatters import MISSING_ACCESSIBLE_TEXT
from src.ui.widgets.data_table.pandas_table_model import PandasTableModel


def _small_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": [1, 2, None, 4],
            "b": ["w", "x", "y", "z"],
            "c": [10.5, 2.25, 30.0, None],
        }
    )


# -- Correctness --------------------------------------------------------


def test_row_and_column_counts(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    assert model.rowCount() == 4
    assert model.columnCount() == 3


def test_dataframe_property_returns_the_same_object_no_copy(
    qapp: QApplication,
) -> None:
    frame = _small_frame()
    model = PandasTableModel(frame)
    assert model.dataframe is frame  # identity, not equality -- no .copy()


def test_display_role_formats_missing_as_em_dash(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    index = model.index(2, 0)  # row 2, column "a" -> None
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == "—"


def test_accessible_text_role_says_missing_not_color_only(
    qapp: QApplication,
) -> None:
    """The M18 acceptance criterion this test exists for: NaN/NaT render
    with a non-color-only AccessibleTextRole of "missing".
    """
    model = PandasTableModel(_small_frame())
    index = model.index(2, 0)
    assert (
        model.data(index, Qt.ItemDataRole.AccessibleTextRole) == MISSING_ACCESSIBLE_TEXT
    )


def test_accessible_text_role_for_a_real_value_is_not_missing(
    qapp: QApplication,
) -> None:
    model = PandasTableModel(_small_frame())
    index = model.index(0, 0)  # value 1
    assert (
        model.data(index, Qt.ItemDataRole.AccessibleTextRole) != MISSING_ACCESSIBLE_TEXT
    )


def test_header_data_horizontal_is_column_name(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    assert model.headerData(1, Qt.Orientation.Horizontal) == "b"


def test_header_data_vertical_tracks_source_row_through_sort(
    qapp: QApplication,
) -> None:
    """A sorted/filtered view still labels rows by their *original*
    position, not 1..N of the current proxy order -- otherwise a user
    loses track of which real row a displayed line came from.
    """
    model = PandasTableModel(_small_frame())
    model.sort(0, Qt.SortOrder.AscendingOrder)  # column "a": [1, 2, None, 4]
    # Ascending puts NaN last: source order becomes 0, 1, 3, 2.
    assert model.headerData(0, Qt.Orientation.Vertical) == "1"  # source row 0
    assert model.headerData(3, Qt.Orientation.Vertical) == "3"  # source row 2


def test_sort_ascending_orders_by_column(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    model.sort(2, Qt.SortOrder.AscendingOrder)  # column "c": [10.5, 2.25, 30.0, NaN]
    values = [
        model.data(model.index(row, 2), Qt.ItemDataRole.DisplayRole)
        for row in range(model.rowCount())
    ]
    assert values == ["2.25", "10.5", "30", "—"]  # NaN sorts last


def test_sort_descending_reverses_order(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    model.sort(2, Qt.SortOrder.DescendingOrder)
    values = [
        model.data(model.index(row, 2), Qt.ItemDataRole.DisplayRole)
        for row in range(model.rowCount())
    ]
    assert values[0] == "30"


def test_set_filter_mask_restricts_visible_rows(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    mask = np.array([True, False, True, False])
    model.set_filter_mask(mask)
    assert model.rowCount() == 2


def test_set_filter_mask_none_shows_every_row_again(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    model.set_filter_mask(np.array([True, False, False, False]))
    assert model.rowCount() == 1
    model.set_filter_mask(None)
    assert model.rowCount() == 4


def test_filter_preserves_active_sort(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    model.sort(0, Qt.SortOrder.AscendingOrder)
    # Keep only rows where "a" is not missing (source rows 0, 1, 3).
    mask = np.array([True, True, False, True])
    model.set_filter_mask(mask)
    values = [
        model.data(model.index(row, 0), Qt.ItemDataRole.DisplayRole)
        for row in range(model.rowCount())
    ]
    assert values == ["1", "2", "4"]  # still ascending after the filter


def test_source_row_count_is_the_full_unfiltered_count(qapp: QApplication) -> None:
    model = PandasTableModel(_small_frame())
    model.set_filter_mask(np.array([True, False, False, False]))
    assert model.rowCount() == 1
    assert model.source_row_count() == 4


def test_sort_on_empty_frame_does_not_raise(qapp: QApplication) -> None:
    model = PandasTableModel(pd.DataFrame({"a": pd.Series([], dtype="float64")}))
    model.sort(0, Qt.SortOrder.AscendingOrder)  # must not raise
    assert model.rowCount() == 0


def test_sort_string_column_with_missing_values_does_not_raise(
    qapp: QApplication,
) -> None:
    """Regression test: a plain np.argsort on an object-dtype column
    containing None mixed with strings raises TypeError ("'<' not
    supported between instances of 'str' and 'NoneType'") -- found while
    building this milestone, before this test existed to catch it.
    """
    frame = pd.DataFrame({"name": ["b", None, "a", "c"]})
    model = PandasTableModel(frame)
    model.sort(0, Qt.SortOrder.AscendingOrder)  # must not raise
    values = [
        model.data(model.index(row, 0), Qt.ItemDataRole.DisplayRole)
        for row in range(model.rowCount())
    ]
    assert values == ["a", "b", "c", "—"]  # missing value last


def test_descending_sort_keeps_missing_values_last_not_first(
    qapp: QApplication,
) -> None:
    """Regression test: a blind order_indices[::-1] for descending sort
    would move ascending-sort's trailing NaN to the *front* instead of
    keeping it last -- found while building this milestone. Missing
    values stay last regardless of sort direction, matching common
    spreadsheet-tool behavior.
    """
    model = PandasTableModel(_small_frame())
    model.sort(2, Qt.SortOrder.DescendingOrder)  # column "c": [10.5, 2.25, 30.0, NaN]
    values = [
        model.data(model.index(row, 2), Qt.ItemDataRole.DisplayRole)
        for row in range(model.rowCount())
    ]
    assert values == ["30", "10.5", "2.25", "—"]


# -- Performance (M18's explicit acceptance criterion) ------------------


def test_construction_and_data_access_meet_the_1m_row_budget(
    qapp: QApplication,
) -> None:
    """Model construction < 500 ms, data() < 50 microseconds per call, on
    a synthetic 1,000,000 x 10 frame -- the exact numbers the plan's
    acceptance criteria specify. Both are real, measured timings, not
    just an assertion the implementation happens to satisfy by
    construction: pandas_table_model.py's own docstring names the O(n)
    per-cell-call failure mode this guards against.
    """
    row_count = 1_000_000
    rng = np.random.default_rng(0)
    frame = pd.DataFrame({f"col_{i}": rng.random(row_count) for i in range(10)})

    start = time.perf_counter()
    model = PandasTableModel(frame)
    construction_seconds = time.perf_counter() - start
    assert (
        construction_seconds < 0.5
    ), f"construction took {construction_seconds * 1000:.1f} ms, budget is 500 ms"

    index = model.index(row_count // 2, 5)
    call_count = 10_000
    start = time.perf_counter()
    for _ in range(call_count):
        model.data(index, Qt.ItemDataRole.DisplayRole)
    elapsed = time.perf_counter() - start
    per_call_microseconds = (elapsed / call_count) * 1_000_000
    assert (
        per_call_microseconds < 50
    ), f"data() took {per_call_microseconds:.1f} us/call, budget is 50 us"

    assert model.dataframe is frame  # still no copy at this scale
