# File: tests/visualization/test_pivot_heatmap.py
"""``HeatmapChart(row_column=..., column_column=...)`` draws a matrix of any two columns, with
numbers in the cells or as a monochrome square grid (phase-4 step 7.10, Tier-1 V29 and V31).

The registry gains no new chart type: the pivot is an option of ``heatmap`` (the correlation
matrix it always drew is unchanged), so these tests pin the option, the two looks, the ordering and
caps, and the refusals.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.advanced_charts import HeatmapChart
from uadas_core.visualization.chart_registry import _register_builtins, get_chart


def _traffic() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "week": [1, 1, 2, 10, 10],
            "weekday": ["mon", "tue", "mon", "mon", "tue"],
            "visits": [5.0, 3.0, 2.0, 8.0, 1.0],
        }
    )


def _pivot(frame: pd.DataFrame | None = None, **kwargs):
    return HeatmapChart.build(
        _traffic() if frame is None else frame,
        row_column="week",
        column_column="weekday",
        **({"value_column": "visits"} | kwargs),
    )


def test_the_pivot_fields_are_optional_columns_and_variant_a_literal() -> None:
    _register_builtins()
    registration = get_chart("heatmap")
    assert registration.required_fields == ()
    assert registration.optional_fields == (
        "row_column",
        "column_column",
        "value_column",
    )
    assert registration.literal_fields == ("variant",)


def test_rows_and_columns_keep_their_natural_order_and_sum_the_values() -> None:
    trace = _pivot().data[0]
    assert trace.type == "heatmap"
    assert list(trace.x) == ["mon", "tue"]
    assert list(trace.y) == ["1", "2", "10"]  # numeric order, not "1", "10", "2"
    z = [list(row) for row in trace.z]
    assert z[0] == [5.0, 3.0]
    assert z[2] == [8.0, 1.0]
    # A combination with no rows is an empty cell, not a zero.
    assert z[1][0] == 2.0 and math.isnan(z[1][1])
    assert trace.hoverongaps is False


def test_without_a_value_column_the_cells_count_rows() -> None:
    trace = HeatmapChart.build(
        _traffic(), row_column="week", column_column="weekday"
    ).data[0]
    assert list(trace.z[0]) == [1, 1]


def test_axes_titles_and_reading_order() -> None:
    figure = _pivot()
    assert figure.layout.title.text == "visits by week and weekday"
    assert figure.layout.xaxis.title.text == "weekday"
    assert figure.layout.yaxis.title.text == "week"
    assert figure.layout.yaxis.autorange == "reversed"  # the first row at the top


def test_numbers_writes_each_value_in_its_cell() -> None:
    trace = _pivot(variant="numbers").data[0]
    assert trace.texttemplate == "%{text}"
    # All whole: no decimals, and an empty cell has no number.
    assert [list(row) for row in trace.text] == [["5", "3"], ["2", ""], ["8", "1"]]
    thousands = _pivot(
        _traffic().assign(visits=[1000.0, 2.0, 3.0, 4.0, 5.0]), variant="numbers"
    )
    assert thousands.data[0].text[0][0] == "1,000"
    fractional = _pivot(
        _traffic().assign(visits=[5.5, 3.0, 2.0, 8.0, 1.0]), variant="numbers"
    )
    assert [list(row) for row in fractional.data[0].text] == [
        ["5.50", "3.00"],
        ["2.00", ""],
        ["8.00", "1.00"],
    ]


def test_grid_is_a_monochrome_grid_of_gapped_cells_with_no_numbers() -> None:
    trace = _pivot(variant="grid").data[0]
    assert trace.xgap == trace.ygap and trace.xgap > 0
    assert trace.texttemplate is None
    assert (
        trace.colorscale[0][1] == "rgb(247,251,255)"
    )  # "Blues": one hue, not a rainbow


def test_an_ordered_category_column_keeps_its_order_not_the_alphabet() -> None:
    days = ["mon", "tue", "wed"]
    frame = pd.DataFrame(
        {
            "week": [1, 1, 1],
            "weekday": pd.Categorical(["wed", "mon", "tue"], days, ordered=True),
            "visits": [3.0, 1.0, 2.0],
        }
    )
    assert list(_pivot(frame).data[0].x) == days


def test_an_axis_past_forty_values_folds_the_smallest_into_other() -> None:
    frame = pd.DataFrame(
        {
            "week": list(range(60)),
            "weekday": ["mon"] * 60,
            "visits": [float(i + 1) for i in range(60)],
        }
    )
    trace = _pivot(frame).data[0]
    assert len(trace.y) == 40
    assert trace.y[-1] == "Other"
    assert sum(row[0] for row in trace.z) == frame["visits"].sum()
    kept = [int(label) for label in trace.y[:-1]]
    assert kept == sorted(kept)  # the kept rows stay in their own order


def test_a_real_other_category_is_added_to_when_the_axis_is_capped() -> None:
    frame = pd.DataFrame(
        {
            "row": ["r"] * 45,
            "column": [f"c{i:02d}" for i in range(44)] + ["Other"],
            "value": [1.0] * 44 + [1000.0],
        }
    )
    trace = HeatmapChart.build(
        frame, row_column="row", column_column="column", value_column="value"
    ).data[0]
    # 39 kept (the real "Other" among them) and the folded six merged into it: no 40th column.
    assert len(trace.x) == 39 and list(trace.x).count("Other") == 1
    cells = dict(zip(trace.x, trace.z[0], strict=True))
    assert cells["Other"] == 1000.0 + 6.0  # its own 1000 plus the six folded columns
    assert sum(trace.z[0]) == frame["value"].sum()


def test_a_cell_whose_values_are_all_missing_is_empty_not_zero() -> None:
    frame = _traffic().assign(visits=[None, 3.0, 2.0, 8.0, 1.0])
    trace = _pivot(frame, variant="numbers").data[0]
    assert math.isnan(trace.z[0][0])
    assert trace.text[0][0] == ""


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"row_column": "week"}, "both"),
        ({"column_column": "weekday"}, "both"),
        ({"value_column": "visits"}, "both"),
        ({"row_column": "week", "column_column": "week"}, "must differ"),
        (
            {"row_column": "week", "column_column": "weekday", "variant": "wave"},
            "not one of",
        ),
        ({"variant": "grid"}, "pivot"),
        ({"row_column": "nope", "column_column": "weekday"}, "nope"),
        (
            {
                "row_column": "week",
                "column_column": "weekday",
                "value_column": "weekday",
            },
            "must be numeric",
        ),
    ],
)
def test_the_option_is_validated(kwargs: dict, message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        HeatmapChart.build(_traffic(), **kwargs)
