# File: tests/visualization/test_grouped_bar.py
"""``BarChart(variant="grouped")`` draws the series side by side, told apart by pattern as well as
colour (phase-4 step 7.6, Tier-1 V14).

The registry gains no new chart type: grouping is an option of ``bar`` (a look, so a literal field
like ``incomplete_from``), so these tests pin the option, the pattern assignment, the refusals,
and that stacked bars are unchanged.
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
            "region": ["north", "north", "south", "south", "south", "east"],
            "channel": ["web", "shop", "web", "shop", "app", "web"],
            "revenue": [10.0, 20.0, 5.0, 8.0, 3.0, 7.0],
        }
    )


def _grouped(frame: pd.DataFrame | None = None):
    return BarChart.build(
        _sales() if frame is None else frame,
        "region",
        value_column="revenue",
        series_column="channel",
        variant="grouped",
    )


def _shapes(figure) -> list[str | None]:
    return [trace.marker.pattern.shape for trace in figure.data]


def test_the_series_sit_side_by_side_not_stacked() -> None:
    figure = _grouped()
    assert figure.layout.barmode == "group"
    # Series are ordered by label, as in the stacked chart: app, shop, web.
    assert [trace.name for trace in figure.data] == ["app", "shop", "web"]
    # Same numbers as the stacked chart: only the arrangement differs.
    stacked = BarChart.build(
        _sales(), "region", value_column="revenue", series_column="channel"
    )
    assert [list(t.y) for t in figure.data] == [list(t.y) for t in stacked.data]


def test_the_first_series_is_solid_and_the_next_are_patterned() -> None:
    assert _shapes(_grouped()) == ["", "/", "."]


def test_patterns_cycle_after_the_eighth_series_and_other_is_last() -> None:
    frame = pd.DataFrame(
        {
            "region": ["a", "a", "b"] * 10,
            "channel": [f"s{i:02d}" for i in range(30)],
            "revenue": list(range(1, 31)),
        }
    )
    figure = _grouped(frame)
    assert len(figure.data) == _MAX_CATEGORIES
    assert figure.data[-1].name == "Other"
    shapes = _shapes(figure)
    assert shapes[0] == shapes[8] == ""  # the cycle is eight long
    assert len(set(shapes)) == 8


def test_stacked_bars_have_no_pattern() -> None:
    figure = BarChart.build(
        _sales(), "region", value_column="revenue", series_column="channel"
    )
    assert figure.layout.barmode == "stack"
    assert _shapes(figure) == [None, None, None]


def test_variant_is_a_literal_field_not_a_column() -> None:
    _register_builtins()
    registration = get_chart("bar")
    assert registration.literal_fields == ("incomplete_from", "variant")
    assert "variant" not in registration.optional_fields


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"series_column": "channel", "variant": "pyramid"}, "not one of"),
        ({"variant": "grouped"}, "give series_column"),
        (
            {
                "series_column": "channel",
                "variant": "grouped",
                "incomplete_from": "north",
            },
            "stacked bars",
        ),
    ],
)
def test_variant_is_validated(kwargs: dict, message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        BarChart.build(_sales(), "region", value_column="revenue", **kwargs)
