# File: tests/visualization/test_dual_axis_line.py
"""``LineChart(y2_column=...)`` draws a second line against a right-hand axis (phase-4 step 7.5, Tier-1 V09).

The registry gains no new chart type: the second axis is an option of ``line`` (a column, so it is
an ``optional_fields`` entry, not a literal), so these tests pin the option, the axis wiring, the
refusals, and that a plain line chart is unchanged.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.chart_registry import _register_builtins, get_chart
from uadas_core.visualization.continuous_charts import (
    _RESAMPLE_THRESHOLD_ROWS,
    LineChart,
)


def _monthly() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "month": pd.date_range("2025-01-01", periods=4, freq="MS"),
            "revenue": [1000.0, 1100.0, 1050.0, 1200.0],
            "conversion": [2.1, 2.4, 2.2, 3.0],
        }
    )


def _dual(**kwargs):
    return LineChart.build(
        _monthly(), "revenue", x_column="month", y2_column="conversion", **kwargs
    )


def test_y2_column_is_an_optional_column_field_of_line() -> None:
    _register_builtins()
    registration = get_chart("line")
    assert registration.optional_fields == ("x_column", "y2_column")
    assert registration.literal_fields == ("variant",)


def test_a_plain_line_chart_has_no_second_axis() -> None:
    figure = LineChart.build(_monthly(), "revenue", x_column="month")
    assert len(figure.data) == 1
    assert "yaxis2" not in figure.to_plotly_json()["layout"]


def test_the_second_column_is_a_second_line_on_a_right_hand_axis() -> None:
    figure = _dual()
    first, second = figure.data
    assert (first.name, second.name) == ("revenue", "conversion")
    assert list(first.y) == [1000.0, 1100.0, 1050.0, 1200.0]
    assert list(second.y) == [2.1, 2.4, 2.2, 3.0]
    assert list(first.x) == list(second.x)
    assert first.yaxis in (None, "y") and second.yaxis == "y2"
    assert figure.layout.yaxis2.overlaying == "y"
    assert figure.layout.yaxis2.side == "right"


def test_each_axis_is_titled_with_its_column_and_only_the_left_has_a_grid() -> None:
    figure = _dual()
    assert figure.layout.yaxis.title.text == "revenue"
    assert figure.layout.yaxis2.title.text == "conversion"
    # Two grids on different scales would not line up: the left axis keeps its own.
    assert figure.layout.yaxis2.showgrid is False
    assert figure.layout.title.text == "revenue and conversion over month"
    assert _dual(title="Acme").layout.title.text == "Acme"


def test_the_second_column_must_exist_be_numeric_and_differ() -> None:
    with pytest.raises(ServiceError, match="nope"):
        LineChart.build(_monthly(), "revenue", x_column="month", y2_column="nope")
    text = _monthly().astype({"conversion": str})
    with pytest.raises(ServiceError, match="'conversion' must be numeric"):
        LineChart.build(text, "revenue", x_column="month", y2_column="conversion")
    with pytest.raises(ServiceError, match="must differ"):
        LineChart.build(_monthly(), "revenue", x_column="month", y2_column="revenue")


def test_the_area_variant_cannot_be_combined_with_a_second_axis() -> None:
    with pytest.raises(ServiceError, match="y2_column"):
        _dual(variant="area")


def test_both_lines_are_downsampled_together_and_stay_on_their_axes() -> None:
    rows = _RESAMPLE_THRESHOLD_ROWS + 1000
    frame = pd.DataFrame(
        {"a": np.sin(np.arange(rows) / 300), "b": np.cos(np.arange(rows) / 300)}
    )
    figure = LineChart.build(frame, "a", y2_column="b")
    assert [t.yaxis for t in figure.data][1] == "y2"
    assert all(len(t.y) < rows for t in figure.data)  # it really was downsampled
    assert figure.data[1].x[-1] == rows - 1
