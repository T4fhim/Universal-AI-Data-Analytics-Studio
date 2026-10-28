# File: tests/visualization/test_categorical_color.py
"""A text ``color_column`` draws one trace per category instead of failing.

Plotly accepts only colours or numbers for ``marker.color``, so handing it a text column raised
``ValueError`` and ``ScatterChart`` / ``BubbleChart`` could not be built with a categorical
colour (the API's ``charts_render`` answered 422). These tests pin the repaired behaviour and
that a numeric colour column is unchanged.
"""

from __future__ import annotations

import pandas as pd

from uadas_core.visualization.advanced_charts import BubbleChart
from uadas_core.visualization.base_chart import category_groups
from uadas_core.visualization.continuous_charts import ScatterChart


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "y": [6.0, 5.0, 4.0, 3.0, 2.0, 1.0],
            "size": [10, 20, 30, 40, 50, 60],
            "cat": ["b", "a", "b", None, "a", "b"],
            "num": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        }
    )


def test_category_groups_orders_by_label_and_keeps_missing_visible() -> None:
    groups = category_groups(_frame(), "cat")
    assert [label for label, _ in groups] == ["(missing)", "a", "b"]
    assert sum(len(group) for _, group in groups) == 6


def test_scatter_text_color_column_gives_one_trace_per_category() -> None:
    figure = ScatterChart.build(_frame(), "x", "y", color_column="cat")
    assert [trace.name for trace in figure.data] == ["(missing)", "a", "b"]
    assert sum(len(trace.x) for trace in figure.data) == 6


def test_scatter_numeric_color_column_stays_one_trace_with_a_scale() -> None:
    figure = ScatterChart.build(_frame(), "x", "y", color_column="num")
    assert len(figure.data) == 1
    assert figure.data[0].marker.showscale is True


def test_bubble_text_color_column_shares_one_size_scale() -> None:
    figure = BubbleChart.build(_frame(), "x", "y", "size", color_column="cat")
    assert [trace.name for trace in figure.data] == ["(missing)", "a", "b"]
    assert len({trace.marker.sizeref for trace in figure.data}) == 1
    assert sum(len(trace.marker.size) for trace in figure.data) == 6


def test_bubble_numeric_color_column_stays_one_trace_with_a_scale() -> None:
    figure = BubbleChart.build(_frame(), "x", "y", "size", color_column="num")
    assert len(figure.data) == 1
    assert figure.data[0].marker.showscale is True
