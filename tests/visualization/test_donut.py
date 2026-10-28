# File: tests/visualization/test_donut.py
"""``PieChart(variant="donut")`` draws a ring with the total in its centre (phase-4 step 7.8,
Tier-1 V25).

The registry gains no new chart type: the ring is an option of ``pie`` (a look, so a literal field
like ``bar``'s ``variant``), so these tests pin the option, what the centre says, and that a plain
pie is unchanged.
"""

from __future__ import annotations

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.categorical_charts import _MAX_CATEGORIES, PieChart
from uadas_core.visualization.chart_registry import _register_builtins, get_chart


def _sales(revenue: list[float] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "channel": ["web", "web", "shop", "app"],
            "revenue": [10.0, 20.0, 5.0, 5.0] if revenue is None else revenue,
        }
    )


def _donut(frame: pd.DataFrame | None = None, **kwargs):
    return PieChart.build(
        _sales() if frame is None else frame,
        "channel",
        variant="donut",
        **kwargs,
    )


def test_a_donut_is_a_pie_with_a_hole() -> None:
    figure = _donut(value_column="revenue")
    assert len(figure.data) == 1
    trace = figure.data[0]
    assert trace.type == "pie"
    assert 0.5 <= trace.hole <= 0.7
    assert dict(zip(trace.labels, trace.values, strict=True)) == {
        "web": 30.0,
        "shop": 5.0,
        "app": 5.0,
    }


def test_the_total_is_written_in_the_centre_with_what_it_totals() -> None:
    figure = _donut(value_column="revenue")
    (note,) = figure.layout.annotations
    assert (note.x, note.y) == (0.5, 0.5)
    assert (note.xref, note.yref) == ("paper", "paper")
    assert note.showarrow is False
    assert "40" in note.text and "revenue" in note.text


def test_whole_totals_have_no_decimals_and_fractional_ones_have_two() -> None:
    whole = _donut(_sales([1000.0, 2000.0, 500.0, 500.0]), value_column="revenue")
    assert "4,000" in whole.layout.annotations[0].text
    fractional = _donut(_sales([10.5, 20.0, 5.0, 4.25]), value_column="revenue")
    assert "39.75" in fractional.layout.annotations[0].text


def test_a_long_total_is_set_smaller_so_it_stays_inside_the_hole() -> None:
    short = _donut(value_column="revenue").layout.annotations[0].text
    long = (
        _donut(_sales([1.5e9, 2.5e9, 5.0e8, 5.0e8]), value_column="revenue")
        .layout.annotations[0]
        .text
    )
    assert "font-size:16px" in short
    assert "font-size:12px" in long


def test_a_column_name_cannot_inject_markup_into_the_centre() -> None:
    frame = _sales().rename(columns={"revenue": "a<b>c"})
    text = _donut(frame, value_column="a<b>c").layout.annotations[0].text
    assert "a&lt;b&gt;c" in text and "<b>c" not in text


def test_without_a_value_column_the_centre_counts_rows() -> None:
    figure = _donut()
    text = figure.layout.annotations[0].text
    assert "4" in text and "Count" in text


def test_the_total_includes_the_slices_folded_into_other() -> None:
    frame = pd.DataFrame({"channel": [f"c{i:02d}" for i in range(30)]})
    figure = _donut(frame)
    assert len(figure.data[0].labels) == _MAX_CATEGORIES
    assert "30" in figure.layout.annotations[0].text


def test_a_donut_refuses_negative_values_its_ring_cannot_show() -> None:
    with pytest.raises(ServiceError, match="negative"):
        _donut(_sales([10.0, -20.0, 5.0, 5.0]), value_column="revenue")


def test_an_infinite_total_does_not_crash_the_centre() -> None:
    figure = _donut(_sales([10.0, float("inf"), 5.0, 5.0]), value_column="revenue")
    assert "inf" in figure.layout.annotations[0].text


def test_a_plain_pie_is_unchanged() -> None:
    figure = PieChart.build(_sales(), "channel", value_column="revenue")
    assert figure.data[0].hole is None
    assert len(figure.layout.annotations) == 0


def test_an_unknown_variant_is_refused() -> None:
    with pytest.raises(ServiceError, match="not one of"):
        PieChart.build(_sales(), "channel", variant="ring")


def test_variant_is_a_literal_field_not_a_column() -> None:
    _register_builtins()
    registration = get_chart("pie")
    assert registration.literal_fields == ("variant",)
    assert "variant" not in registration.optional_fields
