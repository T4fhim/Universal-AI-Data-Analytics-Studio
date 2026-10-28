# File: tests/visualization/test_stacked_bar.py
"""``BarChart(series_column=...)`` draws stacked columns (phase-4 step 7, Tier-1 V11).

The registry gains no new chart type: stacking is an option of ``bar``, so these tests pin the
option itself, its ordering and capping rules, and that a plain bar chart is unchanged.
"""

from __future__ import annotations

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.categorical_charts import _MAX_CATEGORIES, BarChart
from uadas_core.visualization.chart_registry import _register_builtins, get_chart


def _sales() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "month": pd.to_datetime(
                ["2025-03-01", "2025-01-01", "2025-02-01", "2025-01-01", "2025-03-01"]
            ),
            "channel": ["web", "web", "retail", "retail", "retail"],
            "revenue": [30.0, 10.0, 25.0, 5.0, 7.0],
        }
    )


def test_one_stacked_trace_per_series_in_label_order() -> None:
    figure = BarChart.build(
        _sales(), "month", value_column="revenue", series_column="channel"
    )
    assert [trace.name for trace in figure.data] == ["retail", "web"]
    assert figure.layout.barmode == "stack"
    assert sum(float(sum(trace.y)) for trace in figure.data) == 77.0


def test_date_categories_come_out_in_date_order_as_dates() -> None:
    figure = BarChart.build(
        _sales(), "month", value_column="revenue", series_column="channel"
    )
    assert list(figure.data[0].x) == ["2025-01-01", "2025-02-01", "2025-03-01"]
    # A (category, series) pair with no rows is a zero-height segment, not a gap in the arrays.
    assert list(figure.data[1].y) == [10.0, 0.0, 30.0]


def test_counts_rows_when_there_is_no_value_column() -> None:
    figure = BarChart.build(_sales(), "month", series_column="channel")
    assert sum(float(sum(trace.y)) for trace in figure.data) == 5.0
    assert figure.layout.yaxis.title.text == "Count"


def test_series_past_the_cap_fold_into_other_without_losing_the_total() -> None:
    frame = pd.DataFrame(
        {
            "bucket": ["a", "a", "b"] * 10,
            "series": [f"s{i:02d}" for i in range(30)],
            "value": list(range(1, 31)),
        }
    )
    figure = BarChart.build(
        frame, "bucket", value_column="value", series_column="series"
    )
    names = [trace.name for trace in figure.data]
    assert len(names) == _MAX_CATEGORIES
    assert names[-1] == "Other"
    assert sum(float(sum(trace.y)) for trace in figure.data) == float(sum(range(1, 31)))


def test_a_missing_label_is_its_own_visible_series() -> None:
    frame = pd.DataFrame(
        {"bucket": ["a", "a"], "series": ["x", None], "value": [1.0, 2.0]}
    )
    figure = BarChart.build(
        frame, "bucket", value_column="value", series_column="series"
    )
    assert [trace.name for trace in figure.data] == ["(missing)", "x"]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"series_column": "nope"}, r"Column\(s\) not found"),
        ({"series_column": "channel", "value_column": "channel"}, "must be numeric"),
    ],
)
def test_bad_columns_raise_service_error(kwargs: dict, message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        BarChart.build(_sales(), "month", **kwargs)


def test_an_empty_frame_cannot_be_stacked() -> None:
    with pytest.raises(ServiceError, match="no rows"):
        BarChart.build(_sales().iloc[0:0], "month", series_column="channel")


def test_without_a_series_column_it_is_still_one_plain_bar_trace() -> None:
    figure = BarChart.build(_sales(), "channel", value_column="revenue")
    assert len(figure.data) == 1
    assert figure.layout.barmode is None


def test_incomplete_from_collapses_later_buckets_into_one_incomplete_total() -> None:
    figure = BarChart.build(
        _sales(),
        "month",
        value_column="revenue",
        series_column="channel",
        incomplete_from="2025-03-01",
    )
    assert [trace.name for trace in figure.data] == ["retail", "web", "Incomplete"]
    retail, web, incomplete = (list(trace.y) for trace in figure.data)
    assert incomplete == [0.0, 0.0, 37.0]  # March: web 30 + retail 7, no split
    assert retail[-1] == web[-1] == 0.0
    assert sum(sum(y) for y in (retail, web, incomplete)) == 77.0


def test_incomplete_is_never_inferred_from_the_last_bucket() -> None:
    figure = BarChart.build(
        _sales(), "month", value_column="revenue", series_column="channel"
    )
    assert "Incomplete" not in [trace.name for trace in figure.data]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"series_column": "channel", "incomplete_from": "2030-01-01"}, "not one of"),
        ({"incomplete_from": "2025-03-01"}, "give series_column"),
    ],
)
def test_incomplete_from_is_validated(kwargs: dict, message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        BarChart.build(_sales(), "month", value_column="revenue", **kwargs)


def test_the_registry_keeps_columns_and_literals_apart() -> None:
    _register_builtins()
    registration = get_chart("bar")
    assert "series_column" in registration.optional_fields
    assert registration.literal_fields == ("incomplete_from",)
    assert "incomplete_from" not in registration.optional_fields
