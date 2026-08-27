# File: tests/visualization/test_advanced_charts.py
"""Tests for src.visualization.advanced_charts."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from src.core.exceptions import ServiceError
from src.visualization.advanced_charts import (
    BubbleChart,
    FunnelChart,
    HeatmapChart,
    RadarChart,
    TreemapChart,
    WaterfallChart,
)


def _dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "x": [1, 2, 3, 4, 5],
            "y": [5, 4, 3, 2, 1],
            "z": [10, 20, 30, 40, 50],
            "cat": ["a", "b", "a", "b", "a"],
        }
    )


def test_heatmap_chart_builds_figure() -> None:
    fig = HeatmapChart.build(_dataframe())
    assert isinstance(fig, go.Figure)


def test_heatmap_chart_too_few_numeric_columns_raises() -> None:
    df = pd.DataFrame({"cat": ["a", "b"]})
    with pytest.raises(ServiceError):
        HeatmapChart.build(df)


def test_bubble_chart_builds_figure() -> None:
    fig = BubbleChart.build(_dataframe(), "x", "y", "z")
    assert isinstance(fig, go.Figure)


def test_bubble_chart_negative_size_raises() -> None:
    df = _dataframe().assign(z=[-1, 2, 3, 4, 5])
    with pytest.raises(ServiceError, match="negative"):
        BubbleChart.build(df, "x", "y", "z")


def test_treemap_chart_builds_figure() -> None:
    fig = TreemapChart.build(_dataframe(), ["cat"], "z")
    assert isinstance(fig, go.Figure)


def test_treemap_chart_empty_path_columns_raises() -> None:
    with pytest.raises(ServiceError, match="at least one"):
        TreemapChart.build(_dataframe(), [], "z")


def test_radar_chart_builds_figure() -> None:
    fig = RadarChart.build(_dataframe(), "cat", ["x", "y", "z"])
    assert isinstance(fig, go.Figure)
    assert len(fig.data) == len(_dataframe())


def test_radar_chart_too_few_value_columns_raises() -> None:
    with pytest.raises(ServiceError, match="at least 3"):
        RadarChart.build(_dataframe(), "cat", ["x", "y"])


def test_waterfall_chart_builds_figure() -> None:
    fig = WaterfallChart.build(_dataframe(), "cat", "x")
    assert isinstance(fig, go.Figure)


def test_funnel_chart_builds_figure() -> None:
    fig = FunnelChart.build(_dataframe(), "cat", "z")
    assert isinstance(fig, go.Figure)


def test_funnel_chart_negative_value_raises() -> None:
    df = _dataframe().assign(z=[-1, 2, 3, 4, 5])
    with pytest.raises(ServiceError, match="negative"):
        FunnelChart.build(df, "cat", "z")
