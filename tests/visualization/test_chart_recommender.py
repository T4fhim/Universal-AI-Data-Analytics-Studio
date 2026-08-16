# File: tests/visualization/test_chart_recommender.py
"""Tests for src.visualization.chart_recommender."""

from __future__ import annotations

import pandas as pd

from src.visualization.chart_recommender import recommend_charts


def test_recommend_charts_suggests_line_for_date_plus_numeric() -> None:
    df = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=10),
            "sales": range(10),
        }
    )
    suggestions = recommend_charts(df)
    assert suggestions[0].chart_type == "Line"
    assert "date" in suggestions[0].columns
    assert suggestions[0].reason  # always populated


def test_recommend_charts_suggests_scatter_for_two_numeric_columns() -> None:
    df = pd.DataFrame({"a": range(10), "b": range(10, 20)})
    suggestions = recommend_charts(df)
    chart_types = [s.chart_type for s in suggestions]
    assert "Scatter" in chart_types


def test_recommend_charts_suggests_bar_for_low_cardinality_category_plus_numeric() -> (
    None
):
    df = pd.DataFrame({"region": ["east", "west"] * 5, "sales": range(10)})
    suggestions = recommend_charts(df)
    chart_types = [s.chart_type for s in suggestions]
    assert "Bar" in chart_types


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
