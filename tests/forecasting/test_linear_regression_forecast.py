# File: tests/forecasting/test_linear_regression_forecast.py
"""Tests for src.forecasting.linear_regression_forecast."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.core.exceptions import ServiceError
from src.forecasting.linear_regression_forecast import forecast_linear_regression


def _linear_series(n: int = 20) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    return pd.DataFrame({"date": dates, "value": 10 + np.arange(n) * 2.0})


def test_forecast_linear_regression_recovers_known_slope() -> None:
    result = forecast_linear_regression(_linear_series(), "date", "value", periods=5)
    assert result.method == "linear_regression"
    assert len(result.forecast_values) == 5
    # Perfectly linear input -> next value should continue the trend
    # (slope 2/day) almost exactly.
    assert result.forecast_values.iloc[0] == pytest.approx(
        10 + 19 * 2.0 + 2.0, abs=0.01
    )


def test_forecast_linear_regression_rejects_non_positive_periods() -> None:
    with pytest.raises(ServiceError, match="periods must be positive"):
        forecast_linear_regression(_linear_series(), "date", "value", periods=0)


def test_forecast_linear_regression_rejects_invalid_degree() -> None:
    with pytest.raises(ServiceError, match="degree must be between"):
        forecast_linear_regression(
            _linear_series(), "date", "value", periods=5, degree=10
        )


def test_forecast_linear_regression_too_few_observations_for_degree() -> None:
    small = _linear_series(n=3)
    with pytest.raises(ServiceError, match="At least 4"):
        forecast_linear_regression(small, "date", "value", periods=2, degree=3)
