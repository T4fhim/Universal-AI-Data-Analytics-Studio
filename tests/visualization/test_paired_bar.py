# File: tests/visualization/test_paired_bar.py
"""``BarChart(variant="paired")`` draws two series as horizontal bar pairs, with value labels
(phase-4 step 7.7, Tier-1 V15).

The registry gains no new chart type: pairing is an option of ``bar`` (a look, so it shares the
``variant`` literal field with ``"grouped"``), so these tests pin the option, the orientation and
axis wiring, the labels, and the refusals.
"""

from __future__ import annotations

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.categorical_charts import BarChart


def _pairs() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "south", "south", "east"],
            "year": ["2024", "2025", "2024", "2025", "2025"],
            "revenue": [10.0, 12.5, 8.0, 9.0, 4.0],
        }
    )


def _paired(frame: pd.DataFrame | None = None, **kwargs):
    return BarChart.build(
        _pairs() if frame is None else frame,
        "region",
        series_column="year",
        variant="paired",
        **({"value_column": "revenue"} | kwargs),
    )


def test_two_series_become_horizontal_bar_pairs_base_first() -> None:
    figure = _paired()
    assert figure.layout.barmode == "group"
    base, compare = figure.data
    assert (base.name, compare.name) == ("2024", "2025")
    assert base.orientation == compare.orientation == "h"
    # Categories on the y axis in the column's own order, values on x; a pair is missing a
    # value as zero (east has no 2024 row).
    assert list(base.y) == list(compare.y) == ["east", "north", "south"]
    assert list(base.x) == [0.0, 10.0, 8.0]
    assert list(compare.x) == [4.0, 12.5, 9.0]


def test_the_base_is_solid_and_the_comparison_is_hatched() -> None:
    figure = _paired()
    assert [t.marker.pattern.shape for t in figure.data] == ["", "/"]


def test_the_first_category_is_at_the_top_and_the_axes_are_titled() -> None:
    figure = _paired()
    # Horizontal bars start at the bottom by default; reading order is top to bottom.
    assert figure.layout.yaxis.autorange == "reversed"
    assert figure.layout.xaxis.title.text == "revenue"
    assert figure.layout.yaxis.title.text == "region"
    assert figure.layout.title.text == "revenue by region and year"


def test_each_bar_is_labelled_with_its_value() -> None:
    figure = _paired()
    base, compare = figure.data
    assert base.textposition == compare.textposition == "outside"
    assert list(base.text) == ["0.00", "10.00", "8.00"]
    assert list(compare.text) == ["4.00", "12.50", "9.00"]
    # Whole numbers carry no decimals, and thousands are separated.
    whole = _pairs().assign(revenue=[1000.0, 2500.0, 800.0, 900.0, 400.0])
    assert list(_paired(whole).data[1].text) == ["400", "2,500", "900"]


def test_without_a_value_column_the_bars_count_rows() -> None:
    figure = BarChart.build(_pairs(), "region", series_column="year", variant="paired")
    assert figure.layout.xaxis.title.text == "Count"
    assert list(figure.data[1].x) == [1, 1, 1]
    assert list(figure.data[1].text) == ["1", "1", "1"]


def test_one_series_is_refused() -> None:
    only_2025 = _pairs()[lambda f: f["year"] == "2025"]
    with pytest.raises(ServiceError, match="exactly two"):
        _paired(only_2025)


def test_three_series_are_refused() -> None:
    frame = pd.concat([_pairs(), _pairs().assign(year="2026")])
    with pytest.raises(ServiceError, match="exactly two"):
        _paired(frame)


def test_it_cannot_be_combined_with_incomplete_from() -> None:
    with pytest.raises(ServiceError, match="stacked bars"):
        _paired(incomplete_from="north")


def test_it_needs_a_series_column() -> None:
    with pytest.raises(ServiceError, match="give series_column"):
        BarChart.build(_pairs(), "region", value_column="revenue", variant="paired")
