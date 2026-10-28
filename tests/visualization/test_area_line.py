# File: tests/visualization/test_area_line.py
"""``LineChart(variant="area")`` draws an area to the baseline with a dot on the last point
(phase-4 step 7.3, Tier-1 V02).

The registry gains no new chart type: the area is an option of ``line``, so these tests pin the
option, where the end dot lands, and that a plain line chart is unchanged.
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
            "month": pd.date_range("2025-01-01", periods=5, freq="MS"),
            "revenue": [10.0, 12.0, 11.0, 15.0, 14.0],
        }
    )


def _dots(figure) -> list[int]:
    """Positions of the points that are drawn as a marker (a size above zero)."""
    return [i for i, size in enumerate(figure.data[0].marker.size) if size > 0]


def test_a_plain_line_chart_is_unchanged() -> None:
    figure = LineChart.build(_monthly(), "revenue", x_column="month")
    trace = figure.data[0]
    assert trace.mode == "lines"
    assert trace.fill is None
    assert trace.marker.size is None


def test_area_fills_to_the_baseline_and_marks_only_the_last_point() -> None:
    figure = LineChart.build(_monthly(), "revenue", x_column="month", variant="area")
    assert len(figure.data) == 1
    trace = figure.data[0]
    assert trace.fill == "tozeroy"
    assert trace.mode == "lines+markers"
    assert (
        trace.cliponaxis is False
    )  # the dot is on the axis edge: do not cut it in half
    assert _dots(figure) == [4]
    assert list(trace.y) == [10.0, 12.0, 11.0, 15.0, 14.0]


def test_the_dot_sits_on_the_last_value_that_exists() -> None:
    frame = _monthly()
    frame.loc[4, "revenue"] = None
    figure = LineChart.build(frame, "revenue", x_column="month", variant="area")
    assert _dots(figure) == [3]


def test_a_column_with_no_values_draws_no_dot() -> None:
    frame = _monthly().assign(revenue=np.nan)
    figure = LineChart.build(frame, "revenue", x_column="month", variant="area")
    assert _dots(figure) == []


def test_the_dot_survives_resampling_of_a_large_series() -> None:
    rows = _RESAMPLE_THRESHOLD_ROWS + 1000
    frame = pd.DataFrame({"value": np.sin(np.arange(rows) / 300)})
    figure = LineChart.build(frame, "value", variant="area")
    sizes = list(figure.data[0].marker.size)
    assert len(sizes) < rows  # it really was downsampled
    assert sizes[-1] > 0
    assert figure.data[0].x[-1] == rows - 1


def test_an_unknown_variant_is_refused() -> None:
    with pytest.raises(ServiceError, match="not one of"):
        LineChart.build(_monthly(), "revenue", variant="glow")


def test_variant_is_a_literal_field_not_a_column() -> None:
    _register_builtins()
    registration = get_chart("line")
    assert registration.literal_fields == ("variant",)
    assert "variant" not in registration.optional_fields
