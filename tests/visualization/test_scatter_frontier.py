# File: tests/visualization/test_scatter_frontier.py
"""``ScatterChart(frontier=..., label_column=..., pin=...)`` draws the Pareto frontier of the
points and pins one of them (phase-4 step 7.11, Tier-1 scatter with pin and Pareto frontier).

The registry gains no new chart type: the frontier and the pin are options of ``scatter`` (the
frontier and the pin are values, so literal fields; the label column is a column), so these tests
pin the frontier of each corner, the labels, the pin, the refusals, and that a plain scatter is
unchanged.
"""

from __future__ import annotations

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.chart_registry import _register_builtins, get_chart
from uadas_core.visualization.continuous_charts import ScatterChart


def _models() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": ["A", "B", "C", "D", "E", "F"],
            "cost": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "score": [5.0, 8.0, 6.0, 9.0, 4.0, 10.0],
        }
    )


def _scatter(frame: pd.DataFrame | None = None, **kwargs):
    return ScatterChart.build(
        _models() if frame is None else frame, "cost", "score", **kwargs
    )


def _frontier(figure) -> tuple[list[float], list[float]]:
    (trace,) = [t for t in figure.data if t.name == "Pareto frontier"]
    return list(trace.x), list(trace.y)


def test_the_new_fields_are_registered() -> None:
    _register_builtins()
    registration = get_chart("scatter")
    assert registration.optional_fields == ("color_column", "label_column")
    assert registration.literal_fields == ("frontier", "pin")


def test_a_plain_scatter_is_unchanged() -> None:
    figure = _scatter()
    assert len(figure.data) == 1
    assert figure.data[0].text is None


@pytest.mark.parametrize(
    ("corner", "expected"),
    [
        # The best corner is where a point is cheap and scores high, and so on.
        ("upper_left", ([1.0, 2.0, 4.0, 6.0], [5.0, 8.0, 9.0, 10.0])),
        ("upper_right", ([6.0], [10.0])),
        ("lower_left", ([1.0, 5.0], [5.0, 4.0])),
        ("lower_right", ([5.0, 6.0], [4.0, 10.0])),
    ],
)
def test_the_frontier_is_the_points_no_other_point_beats(
    corner: str, expected: tuple[list[float], list[float]]
) -> None:
    assert _frontier(_scatter(frontier=corner)) == expected


def test_the_frontier_is_a_dashed_line_without_markers_after_the_points() -> None:
    figure = _scatter(frontier="upper_left")
    points, frontier = figure.data
    assert points.mode == "markers"
    assert frontier.mode == "lines"
    assert frontier.line.dash == "dash"


def test_rows_with_a_missing_coordinate_are_left_out_of_the_frontier() -> None:
    frame = _models()
    frame.loc[5, "score"] = None  # F, the best point
    xs, ys = _frontier(_scatter(frame, frontier="upper_left"))
    assert xs == [1.0, 2.0, 4.0] and ys == [5.0, 8.0, 9.0]


def test_the_frontier_covers_all_the_points_not_one_colour_group() -> None:
    frame = _models().assign(group=["g1", "g2", "g1", "g2", "g1", "g2"])
    figure = _scatter(frame, color_column="group", frontier="upper_left")
    assert [t.name for t in figure.data] == ["g1", "g2", "Pareto frontier"]
    assert _frontier(figure)[0] == [1.0, 2.0, 4.0, 6.0]


def test_label_column_names_each_point() -> None:
    figure = _scatter(label_column="name")
    assert list(figure.data[0].text) == ["A", "B", "C", "D", "E", "F"]


def test_the_pin_is_a_labelled_ring_on_top_of_its_point() -> None:
    figure = _scatter(label_column="name", pin="C")
    pinned = figure.data[-1]
    assert pinned.name == "Pinned: C"
    assert (list(pinned.x), list(pinned.y)) == ([3.0], [6.0])
    assert list(pinned.text) == ["C"]
    assert pinned.mode == "markers+text"
    assert pinned.showlegend is False  # it is labelled on the chart itself


def test_frontier_and_pin_together_keep_the_order_points_frontier_pin() -> None:
    figure = _scatter(label_column="name", pin="B", frontier="upper_left")
    assert [t.name for t in figure.data] == ["Points", "Pareto frontier", "Pinned: B"]


def test_rows_joined_from_several_tables_keep_their_labels_aligned() -> None:
    # The same 0..5 index twice: a lookup of labels by index would return twice the rows.
    frame = pd.concat([_models().assign(group="g1"), _models().assign(group="g2")])
    assert frame.index.is_unique is False
    figure = _scatter(frame, color_column="group", label_column="name", pin="C")
    g1, g2, pinned = figure.data
    for trace in (g1, g2):
        assert len(trace.text) == len(trace.x) == 6
    assert list(g2.text) == ["A", "B", "C", "D", "E", "F"]
    assert list(pinned.x) == [3.0, 3.0]  # C appears in both halves


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"label_column": "name", "pin": ""}, "not an empty"),
        ({"frontier": "middle"}, "not one of"),
        ({"pin": "C"}, "give label_column"),
        ({"label_column": "name", "pin": "Z"}, "not one of the values"),
        ({"label_column": "nope"}, "nope"),
    ],
)
def test_the_options_are_validated(kwargs: dict, message: str) -> None:
    with pytest.raises(ServiceError, match=message):
        _scatter(**kwargs)
