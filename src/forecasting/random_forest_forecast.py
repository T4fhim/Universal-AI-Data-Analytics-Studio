# File: src/forecasting/random_forest_forecast.py
"""Random Forest forecast over lagged values, via scikit-learn.

Unlike this package's other forecasters, a Random Forest has no native
notion of "time" — it is a general regressor. This module turns the
series into a supervised-learning problem by using each point's
``n_lags`` preceding values as features to predict the next value
(a standard "windowed" or "lag" feature construction for applying
tabular ML models to time series). Forecasting more than one step
ahead is done recursively: each predicted value is fed back in as a
lag for predicting the next one, since the model was only trained to
predict one step ahead at a time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.forecasting.exponential_smoothing import ForecastResult
from src.forecasting.forecast_input import validate_time_series

_logger = get_logger(__name__)

_DEFAULT_N_LAGS = 3


def _build_lag_features(
    values: np.ndarray, n_lags: int
) -> tuple[np.ndarray, np.ndarray]:
    """Build a ``(n_lags features, 1 target)`` supervised dataset from a 1-D series."""
    rows = []
    targets = []
    for i in range(n_lags, len(values)):
        rows.append(values[i - n_lags : i])
        targets.append(values[i])
    return np.array(rows), np.array(targets)


def forecast_random_forest(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
    periods: int,
    n_lags: int = _DEFAULT_N_LAGS,
    n_estimators: int = 100,
    random_state: int = 42,
) -> ForecastResult:
    """Forecast ``periods`` steps ahead using a Random Forest over lagged values.

    Args:
        dataframe: The source data.
        date_column: Column to use as the time axis.
        value_column: Numeric column to forecast.
        periods: How many future periods to project.
        n_lags: How many preceding values are used as features to
            predict the next one. Defaults to 3.
        n_estimators: Number of trees in the forest.
        random_state: Seed for reproducible results across repeated
            calls with the same data — same convention as
            :func:`~src.analysis.clustering.k_means_clustering`.

    Raises:
        ServiceError: If the underlying data fails
            :func:`~src.forecasting.forecast_input.validate_time_series`,
            ``periods`` is not positive, ``n_lags`` is not positive, or
            there are fewer than ``n_lags + 5`` observations (too few
            lagged training examples to fit a meaningful forest).
    """
    if periods <= 0:
        raise ServiceError(f"periods must be positive; got {periods}.")
    if n_lags <= 0:
        raise ServiceError(f"n_lags must be positive; got {n_lags}.")

    validated = validate_time_series(dataframe, date_column, value_column)
    working = validated.dataframe

    min_required = n_lags + 5
    if len(working) < min_required:
        raise ServiceError(
            f"At least {min_required} observations are required to "
            f"fit a Random Forest forecaster with n_lags={n_lags}; "
            f"found {len(working)}."
        )

    values = working[value_column].to_numpy(dtype=float)
    features, targets = _build_lag_features(values, n_lags)

    model = RandomForestRegressor(n_estimators=n_estimators, random_state=random_state)
    model.fit(features, targets)

    # Recursive multi-step forecasting: each prediction becomes part of
    # the lag window for the next one, since the model was trained to
    # predict exactly one step ahead — see this module's own docstring
    # for why this differs from the other forecasters here.
    history = list(values[-n_lags:])
    forecast_values = []
    for _ in range(periods):
        window = np.array(history[-n_lags:]).reshape(1, -1)
        next_value = float(model.predict(window)[0])
        forecast_values.append(next_value)
        history.append(next_value)

    dates = pd.DatetimeIndex(working[date_column])
    inferred_freq = pd.infer_freq(dates) or "D"
    forecast_dates = pd.date_range(
        start=dates[-1], periods=periods + 1, freq=inferred_freq
    )[1:]

    _logger.info(
        "Random Forest forecast (n_lags=%d, n_estimators=%d): %d "
        "historical point(s), %d period(s) projected.",
        n_lags,
        n_estimators,
        len(working),
        periods,
    )

    return ForecastResult(
        historical_dates=working[date_column],
        historical_values=working[value_column],
        forecast_dates=forecast_dates,
        forecast_values=pd.Series(forecast_values, index=forecast_dates),
        method="random_forest",
    )
