# File: tests/visualization/test_chart_recommender.py
"""Tests for src.visualization.chart_recommender."""

from __future__ import annotations

import itertools

import pandas as pd
import pytest

from src.visualization.chart_recommender import recommend_charts
from src.visualization.chart_registry import get_chart


def test_recommend_charts_suggests_line_for_date_plus_numeric() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=10),
            "sales": range(10),
        }
    )
    suggestions = recommend_charts(df)
    # Milestone 24: chart_type is a chart_registry key ("line"), not a
    # title-cased display string ("Line") -- see ChartSuggestion.chart_type's
    # own docstring for why this was a bug, not a style choice.
    assert suggestions[0].chart_type == "line"
    assert "date" in suggestions[0].columns
    assert suggestions[0].reason  # always populated


def test_recommend_charts_suggests_scatter_for_two_numeric_columns() -> None:
    df = pd.DataFrame({"a": range(10), "b": range(10, 20)})
    suggestions = recommend_charts(df)
    chart_types = [s.chart_type for s in suggestions]
    assert "scatter" in chart_types


def test_recommend_charts_suggests_bar_for_low_cardinality_category_plus_numeric() -> (
    None
):
    df = pd.DataFrame({"region": ["east", "west"] * 5, "sales": range(10)})
    suggestions = recommend_charts(df)
    chart_types = [s.chart_type for s in suggestions]
    assert "bar" in chart_types


# Milestone 24 acceptance criterion: "chart_recommender.recommend_charts()
# output resolves in chart_registry for every suggestion -- the display-
# name/registry-key mismatch is fixed and tested." Rather than hand-picking
# one dataframe, this drives every rule in recommend_charts by combining
# every kind of column recommend_charts inspects (datetime, 2+ numeric,
# low-cardinality categorical) across every subset that could plausibly
# trigger a given branch, so a future rule added there without updating its
# chart_type to a real registry key fails here immediately.
_CANDIDATE_FRAMES: list[pd.DataFrame] = [
    pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=10),
            "sales": range(10),
            "profit": range(10, 20),
            "region": ["east", "west"] * 5,
        }
    ),
    pd.DataFrame({"a": range(10), "b": range(10, 20)}),
    pd.DataFrame({"region": ["east", "west", "north"] * 4, "sales": range(12)}),
    pd.DataFrame({"region": ["east", "west", "north"] * 4}),
    pd.DataFrame({"value": range(20)}),
]


@pytest.mark.parametrize("dataframe", _CANDIDATE_FRAMES)
def test_every_recommendation_resolves_in_the_chart_registry(
    dataframe: pd.DataFrame,
) -> None:
    for suggestion in recommend_charts(dataframe, max_suggestions=100):
        # get_chart() raises ServiceError for an unknown name -- a bare,
        # unguarded call is the assertion here.
        get_chart(suggestion.chart_type)


def test_every_recommend_charts_branch_is_covered_by_the_candidate_frames() -> None:
    """Sanity check on the fixture set above, not recommend_charts itself:
    fails loudly if a future edit to _CANDIDATE_FRAMES stops exercising one
    of recommend_charts's seven suggestion kinds, which would silently
    weaken test_every_recommendation_resolves_in_the_chart_registry's
    per-dataframe coverage."""
    all_suggestions = itertools.chain.from_iterable(
        recommend_charts(df, max_suggestions=100) for df in _CANDIDATE_FRAMES
    )
    seen_types = {s.chart_type for s in all_suggestions}
    assert seen_types == {
        "line",
        "scatter",
        "heatmap",
        "bar",
        "pie",
        "histogram",
        "box_plot",
    }


def test_recommend_charts_empty_dataframe_returns_empty_list() -> None:
    assert recommend_charts(pd.DataFrame()) == []


def test_recommend_charts_respects_max_suggestions() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=10),
            "sales": range(10),
            "profit": range(10, 20),
            "region": ["east", "west"] * 5,
        }
    )
    suggestions = recommend_charts(df, max_suggestions=2)
    assert len(suggestions) == 2


def test_recommend_charts_results_sorted_best_first() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=10),
            "sales": range(10),
            "profit": range(10, 20),
            "region": ["east", "west"] * 5,
        }
    )
    suggestions = recommend_charts(df)
    scores = [s.score for s in suggestions]
    assert scores == sorted(scores, reverse=True)
