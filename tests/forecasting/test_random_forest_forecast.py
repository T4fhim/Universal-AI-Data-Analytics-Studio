# File: tests/forecasting/test_random_forest_forecast.py
"""Tests for src.forecasting.random_forest_forecast."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.core.exceptions import ServiceError
from src.forecasting.random_forest_forecast import forecast_random_forest


def _trending_series(n: int = 30) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    values = 10 + np.arange(n) * 0.5
    return pd.DataFrame({"date": dates, "value": values})


def test_forecast_random_forest_returns_requested_periods() -> None:
    result = forecast_random_forest(_trending_series(), "date", "value", periods=5)
    assert result.method == "random_forest"
    assert len(result.forecast_values) == 5


def test_forecast_random_forest_rejects_non_positive_n_lags() -> None:
    with pytest.raises(ServiceError, match="n_lags must be positive"):
        forecast_random_forest(_trending_series(), "date", "value", periods=5, n_lags=0)


def test_forecast_random_forest_too_few_observations_raises() -> None:
    small = _trending_series(n=5)
    with pytest.raises(ServiceError, match="At least"):
        forecast_random_forest(small, "date", "value", periods=2, n_lags=3)


def test_forecast_random_forest_rejects_non_positive_periods() -> None:
    with pytest.raises(ServiceError, match="periods must be positive"):
        forecast_random_forest(_trending_series(), "date", "value", periods=0)
