# File: tests/visualization/test_forecast_charts.py
"""Tests for src.visualization.forecast_charts.ForecastChart -- milestone 25's own chart type.

Uses real ForecastResult objects produced by real forecasters (not hand-built fixtures) so this
test exercises the exact shape src.ui.results.renderers.forecasting hands to ForecastChart.build
in the running application.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import pytest

from src.core.exceptions import ServiceError
from src.forecasting.exponential_smoothing import forecast_exponential_smoothing
from src.forecasting.linear_regression_forecast import forecast_linear_regression
from src.visualization.forecast_charts import ForecastChart


def _series(n: int = 12) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    values = [10.0 + i for i in range(n)]
    return pd.DataFrame({"date": dates, "value": values})


def test_build_with_a_single_forecast_result_returns_a_figure() -> None:
    dataframe = _series()
    result = forecast_exponential_smoothing(dataframe, "date", "value", periods=5)

    fig = ForecastChart.build(dataframe, "date", "value", [result])

    assert isinstance(fig, go.Figure)
    trace_names = [trace.name for trace in fig.data]
    assert trace_names == ["Historical", "Exponential Smoothing"]


def test_build_with_multiple_candidates_overlays_every_one_and_marks_the_winner() -> (
    None
):
    dataframe = _series()
    exp_smoothing = forecast_exponential_smoothing(
        dataframe, "date", "value", periods=5
    )
    linear = forecast_linear_regression(dataframe, "date", "value", periods=5)

    fig = ForecastChart.build(
        dataframe,
        "date",
        "value",
        [exp_smoothing, linear],
        winner_method="linear_regression",
    )

    trace_names = [trace.name for trace in fig.data]
    assert trace_names == [
        "Historical",
        "Exponential Smoothing",
        "Linear Regression (Winner)",
    ]

    # Non-color-only distinction (A7): the winner's trace is visibly thicker than a
    # non-winning candidate's, not merely a different color.
    winner_trace = fig.data[2]
    loser_trace = fig.data[1]
    assert winner_trace.line.width > loser_trace.line.width


def test_build_with_no_forecast_results_raises_service_error() -> None:
    with pytest.raises(ServiceError, match="At least one forecast result"):
        ForecastChart.build(_series(), "date", "value", [])


def test_build_raises_when_a_named_column_is_missing() -> None:
    dataframe = _series()
    result = forecast_exponential_smoothing(dataframe, "date", "value", periods=5)

    with pytest.raises(ServiceError, match="not found"):
        ForecastChart.build(dataframe, "not_a_column", "value", [result])


def test_default_title_names_the_single_method() -> None:
    dataframe = _series()
    result = forecast_exponential_smoothing(dataframe, "date", "value", periods=5)

    fig = ForecastChart.build(dataframe, "date", "value", [result])

    assert fig.layout.title.text == "Exponential Smoothing Forecast"


def test_default_title_for_multiple_candidates_names_the_comparison() -> None:
    dataframe = _series()
    exp_smoothing = forecast_exponential_smoothing(
        dataframe, "date", "value", periods=5
    )
    linear = forecast_linear_regression(dataframe, "date", "value", periods=5)

    fig = ForecastChart.build(dataframe, "date", "value", [exp_smoothing, linear])

    assert fig.layout.title.text == "Forecast Model Comparison"
