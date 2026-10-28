# File: tests/visualization/test_kpi.py
"""``KpiChart`` draws a KPI card: the latest value, its change, and a mini chart of the series
(phase-4 step 7.12, Tier-1 V21).

A new registry type, because a card is neither of the existing chart shapes: one number with a
delta over a small chart. These tests pin the registration, the card's numbers, the four mini
charts, and the refusals.
"""

from __future__ import annotations

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.advanced_charts import KpiChart
from uadas_core.visualization.chart_registry import _register_builtins, get_chart


def _monthly(values: list[float | None] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "month": pd.date_range("2025-01-01", periods=6, freq="MS"),
            "revenue": (
                [10.0, 12.0, 11.0, 15.0, 14.0, 18.0] if values is None else values
            ),
        }
    )


def _kpi(frame: pd.DataFrame | None = None, **kwargs):
    return KpiChart.build(
        _monthly() if frame is None else frame, "revenue", x_column="month", **kwargs
    )


def test_it_is_registered_with_a_value_column_and_a_look() -> None:
    _register_builtins()
    registration = get_chart("kpi")
    assert registration.chart_class is KpiChart
    assert registration.required_fields == ("value_column",)
    assert registration.optional_fields == ("x_column",)
    assert registration.literal_fields == ("variant",)


def test_the_card_shows_the_latest_value_and_its_change_from_the_one_before() -> None:
    mini, card = _kpi().data
    assert card.type == "indicator"
    assert card.mode == "number+delta"
    assert card.value == 18.0
    assert card.delta.reference == 14.0
    assert card.title.text == "revenue"
    assert mini.type == "scatter"


def test_a_series_of_one_value_has_no_change() -> None:
    card = _kpi(_monthly().iloc[:1]).data[-1]
    assert card.mode == "number"
    assert card.value == 10.0


def test_the_latest_value_is_the_last_one_that_exists() -> None:
    card = _kpi(_monthly([10.0, 12.0, 11.0, 15.0, 14.0, None])).data[-1]
    assert (card.value, card.delta.reference) == (14.0, 15.0)


def test_whole_numbers_have_no_decimals_and_fractional_ones_two() -> None:
    assert _kpi().data[-1].number.valueformat == ",.0f"
    fractional = _kpi(_monthly([10.0, 12.0, 11.0, 15.0, 14.0, 18.5]))
    assert fractional.data[-1].number.valueformat == ",.2f"
    assert fractional.data[-1].delta.valueformat == ",.2f"


def test_the_card_sits_above_a_mini_chart_with_no_axes() -> None:
    figure = _kpi()
    _mini, card = figure.data
    assert card.domain.y[0] >= 0.5
    assert figure.layout.xaxis.visible is False
    assert figure.layout.yaxis.visible is False
    assert figure.layout.yaxis.domain[1] <= card.domain.y[0]
    assert figure.layout.showlegend is False


def test_the_line_look_marks_the_latest_point_with_a_dot() -> None:
    mini = _kpi().data[0]
    assert mini.mode == "lines+markers"
    sizes = list(mini.marker.size)
    assert sizes[-1] > 0 and sum(1 for s in sizes if s > 0) == 1


def test_the_bars_look_is_one_bar_trace() -> None:
    mini = _kpi(variant="bars").data[0]
    assert mini.type == "bar"
    assert list(mini.y) == [10.0, 12.0, 11.0, 15.0, 14.0, 18.0]


def test_the_dashes_look_is_bars_in_a_dash_pattern() -> None:
    mini = _kpi(variant="dashes").data[0]
    assert mini.type == "bar"
    assert mini.marker.pattern.shape == "-"


def test_the_lollipop_look_is_one_trace_of_stems_with_a_dot_on_each_head() -> None:
    figure = _kpi(variant="lollipop")
    stems, card = figure.data
    assert card.type == "indicator"
    assert stems.mode == "lines+markers"
    # Each stem goes from zero up to its value, with a gap before the next one; only the head of
    # a stem has a dot (a size above zero), the foot and the gap have none.
    assert list(stems.y[:6]) == [0, 10.0, None, 0, 12.0, None]
    assert list(stems.marker.size[:6]) == [0, 6, 0, 0, 6, 0]


def test_the_latest_value_is_the_latest_period_not_the_last_row() -> None:
    frame = _monthly().iloc[[3, 0, 5, 1, 4, 2]].reset_index(drop=True)  # shuffled rows
    mini, card = _kpi(frame).data
    assert (card.value, card.delta.reference) == (18.0, 14.0)
    assert list(mini.y) == [10.0, 12.0, 11.0, 15.0, 14.0, 18.0]  # drawn in period order


def test_a_row_with_no_period_is_left_out() -> None:
    frame = _monthly()
    frame.loc[5, "month"] = None
    card = _kpi(frame).data[-1]
    assert card.value == 14.0  # the 18.0 row had no period


def test_an_infinite_value_does_not_crash_the_number_format() -> None:
    card = _kpi(_monthly([10.0, 12.0, 11.0, 15.0, 14.0, float("inf")])).data[-1]
    assert card.value == float("inf")


def test_without_an_x_column_the_row_order_is_the_x_axis() -> None:
    mini, _card = KpiChart.build(_monthly(), "revenue").data
    assert list(mini.x) == [0, 1, 2, 3, 4, 5]


def test_the_title_is_optional_and_a_column_name_cannot_inject_markup() -> None:
    assert _kpi(title="Q1").layout.title.text == "Q1"
    frame = _monthly().rename(columns={"revenue": "a<b>c"})
    card = KpiChart.build(frame, "a<b>c").data[-1]
    assert "a&lt;b&gt;c" in card.title.text and "<b>c" not in card.title.text


@pytest.mark.parametrize(
    ("frame", "kwargs", "message"),
    [
        (None, {"variant": "radar"}, "not one of"),
        (None, {"x_column": "nope"}, "nope"),
        (_monthly().astype({"revenue": str}), {}, "must be numeric"),
        (_monthly([float("nan")] * 6), {}, "no values"),
    ],
)
def test_the_inputs_are_validated(frame, kwargs: dict, message: str) -> None:
    frame = _monthly() if frame is None else frame
    with pytest.raises(ServiceError, match=message):
        KpiChart.build(frame, "revenue", **kwargs)
