# File: tests/forecasting/test_arima_forecast.py
"""Tests for src.forecasting.arima_forecast."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.core.exceptions import ServiceError
from src.forecasting.arima_forecast import forecast_arima


def _trending_series(n: int = 30) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    rng = np.random.default_rng(5)
    values = 10 + np.arange(n) * 0.5 + rng.normal(0, 0.5, n)
    return pd.DataFrame({"date": dates, "value": values})


def test_forecast_arima_returns_requested_periods() -> None:
    result = forecast_arima(_trending_series(), "date", "value", periods=5)
    assert result.method == "arima"
    assert len(result.forecast_values) == 5


def test_forecast_arima_seasonal_requires_seasonal_periods() -> None:
    with pytest.raises(ServiceError, match="seasonal_periods is required"):
        forecast_arima(_trending_series(), "date", "value", periods=5, seasonal=True)


def test_forecast_arima_too_few_observations_raises() -> None:
    small = _trending_series(n=5)
    with pytest.raises(ServiceError, match="At least 10"):
        forecast_arima(small, "date", "value", periods=2)


def test_forecast_arima_rejects_non_positive_periods() -> None:
    with pytest.raises(ServiceError, match="periods must be positive"):
        forecast_arima(_trending_series(), "date", "value", periods=-1)
