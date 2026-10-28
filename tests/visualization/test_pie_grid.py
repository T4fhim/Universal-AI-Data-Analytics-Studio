# File: tests/visualization/test_pie_grid.py
"""``PieChart(panel_column=...)`` draws one pie per value of a column, in a grid (phase-4 step 7.9,
Tier-1 V26).

The registry gains no new chart type: the grid is an option of ``pie`` (a column, so an
``optional_fields`` entry), so these tests pin the option, the grid's shape, that every pie shares
one set of slices (so one colour per category and one legend), the caps, and the refusals.
"""

from __future__ import annotations

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.categorical_charts import _MAX_CATEGORIES, PieChart
from uadas_core.visualization.chart_registry import _register_builtins, get_chart


def _sales() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["north", "north", "north", "south", "south", "east"],
            "channel": ["web", "shop", "web", "web", "app", "shop"],
            "revenue": [10.0, 20.0, 5.0, 8.0, 3.0, 7.0],
        }
    )


def _grid(frame: pd.DataFrame | None = None, **kwargs):
    return PieChart.build(
        _sales() if frame is None else frame,
        "channel",
        panel_column="region",
        **({"value_column": "revenue"} | kwargs),
    )


def _panels(count: int, categories: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": [f"r{p:02d}" for p in range(count) for _ in range(categories)],
            "channel": [f"c{c:02d}" for _ in range(count) for c in range(categories)],
            "revenue": [
                float(p + c + 1) for p in range(count) for c in range(categories)
            ],
        }
    )


def test_panel_column_is_an_optional_column_field_of_pie() -> None:
    _register_builtins()
    registration = get_chart("pie")
    assert registration.optional_fields == ("value_column", "panel_column")
    assert registration.literal_fields == ("variant",)


def test_one_pie_per_panel_value_each_named_after_it() -> None:
    figure = _grid()
    assert [t.type for t in figure.data] == ["pie"] * 3
    assert [t.name for t in figure.data] == ["east", "north", "south"]
    titles = [note.text for note in figure.layout.annotations]
    assert titles == ["east", "north", "south"]


def test_every_pie_has_the_same_slices_in_the_same_order() -> None:
    figure = _grid()
    for trace in figure.data:
        assert list(trace.labels) == ["app", "shop", "web"]
        assert (
            trace.sort is False
        )  # a pie's own sort would give one category two colours
    by_panel = {t.name: list(t.values) for t in figure.data}
    # A category a panel has no rows for is a zero-size slice, not a missing one.
    assert by_panel == {
        "east": [0.0, 7.0, 0.0],
        "north": [0.0, 20.0, 15.0],
        "south": [3.0, 0.0, 8.0],
    }


def test_a_panel_value_cannot_inject_markup_into_its_title() -> None:
    frame = _sales().assign(region=["a<b>c"] * 3 + ["south", "south", "east"])
    titles = [note.text for note in _grid(frame).layout.annotations]
    assert "a&lt;b&gt;c" in titles
    assert not any("<b>" in text for text in titles)


def test_each_pie_sits_below_the_top_of_the_plot_so_titles_clear_the_legend() -> None:
    figure = _grid(_panels(12))
    assert max(t.domain.y[1] for t in figure.data) < 1
    assert all(note.y <= 1 for note in figure.layout.annotations)


def test_only_the_first_pie_lists_the_slices_in_the_legend() -> None:
    figure = _grid()
    assert [t.showlegend for t in figure.data] == [True, False, False]


def test_a_twelve_panel_grid_is_four_columns_by_three_rows() -> None:
    figure = _grid(_panels(12))
    columns = {tuple(t.domain.x) for t in figure.data}
    rows = {tuple(t.domain.y) for t in figure.data}
    assert (len(columns), len(rows)) == (4, 3)


def test_a_few_panels_make_one_row() -> None:
    figure = _grid()
    assert len({tuple(t.domain.y) for t in figure.data}) == 1


def test_panels_past_twelve_fold_into_other_without_losing_the_total() -> None:
    frame = _panels(20)
    figure = _grid(frame)
    assert len(figure.data) == 12
    assert figure.data[-1].name == "Other"
    assert sum(float(sum(t.values)) for t in figure.data) == frame["revenue"].sum()


def test_slices_past_the_cap_fold_into_other_in_every_pie() -> None:
    frame = _panels(2, categories=30)
    figure = _grid(frame)
    for trace in figure.data:
        assert len(trace.labels) == _MAX_CATEGORIES
        assert trace.labels[-1] == "Other"


def test_without_a_value_column_the_slices_count_rows() -> None:
    figure = PieChart.build(_sales(), "channel", panel_column="region")
    assert {t.name: list(t.values) for t in figure.data}["north"] == [0, 1, 2]


def test_the_title_names_the_columns() -> None:
    assert _grid().layout.title.text == "Distribution of channel by region"
    assert _grid(title="Acme").layout.title.text == "Acme"


def test_a_plain_pie_is_unchanged() -> None:
    figure = PieChart.build(_sales(), "channel", value_column="revenue")
    assert len(figure.data) == 1
    assert figure.layout.title.text == "Distribution of channel"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"panel_column": "nope"}, "nope"),
        ({"panel_column": "channel"}, "must differ"),
        ({"panel_column": "region", "variant": "donut"}, "donut"),
    ],
)
def test_the_option_is_validated(kwargs: dict, message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        PieChart.build(_sales(), "channel", value_column="revenue", **kwargs)
