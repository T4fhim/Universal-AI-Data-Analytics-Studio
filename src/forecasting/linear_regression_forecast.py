# File: src/forecasting/linear_regression_forecast.py
"""Linear/polynomial trend forecast, via scikit-learn.

The simplest of this package's forecasters: fits a polynomial trend
against elapsed time (in days from the series' first date) and
projects it forward. No seasonality component at all — unlike
:mod:`~src.forecasting.exponential_smoothing` and
:mod:`~src.forecasting.prophet_forecast`, this method assumes the
series' behavior is governed purely by a smooth trend, which makes it
a fast, interpretable baseline (and a useful contrast candidate in
:mod:`~src.forecasting.model_comparison`) for series that genuinely
are trend-dominated, and a poor choice for anything with real
periodicity.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.forecasting.exponential_smoothing import ForecastResult
from src.forecasting.forecast_input import validate_time_series

_logger = get_logger(__name__)

_MAX_DEGREE = 5


def forecast_linear_regression(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
    periods: int,
    degree: int = 1,
) -> ForecastResult:
    """Forecast ``periods`` steps ahead by fitting a polynomial trend against elapsed time.

    Args:
        dataframe: The source data.
        date_column: Column to use as the time axis.
        value_column: Numeric column to forecast.
        periods: How many future periods to project.
        degree: Polynomial degree. ``1`` (default) fits a straight
            line; higher values fit a curve. Values above 3 are rarely
            useful for forecasting (they tend to fit historical noise
            rather than genuine trend, and extrapolate wildly beyond
            the observed range) but are not rejected outright — the
            hard ceiling here (:data:`_MAX_DEGREE`) exists only to
            catch a clearly mistaken value, not to enforce a stylistic
            opinion.

    Raises:
        ServiceError: If the underlying data fails
            :func:`~src.forecasting.forecast_input.validate_time_series`,
            ``periods`` is not positive, ``degree`` is not a positive
            integer up to 5, or there are fewer observations than
            ``degree + 1`` (an underdetermined polynomial fit).
    """
    if periods <= 0:
        raise ServiceError(f"periods must be positive; got {periods}.")
    if degree < 1 or degree > _MAX_DEGREE:
        raise ServiceError(f"degree must be between 1 and {_MAX_DEGREE}; got {degree}.")

    validated = validate_time_series(dataframe, date_column, value_column)
    working = validated.dataframe

    if len(working) < degree + 1:
        raise ServiceError(
            f"At least {degree + 1} observations are required to fit "
            f"a degree-{degree} polynomial; found {len(working)}."
        )

    dates = pd.DatetimeIndex(working[date_column])
    elapsed_days = (dates - dates[0]).days.to_numpy().reshape(-1, 1)
    values = working[value_column].to_numpy()

    poly = PolynomialFeatures(degree=degree, include_bias=False)
    features = poly.fit_transform(elapsed_days)

    model = LinearRegression()
    model.fit(features, values)

    inferred_freq = pd.infer_freq(dates) or "D"
    forecast_dates = pd.date_range(
        start=dates[-1], periods=periods + 1, freq=inferred_freq
    )[1:]
    forecast_elapsed_days = (forecast_dates - dates[0]).days.to_numpy().reshape(-1, 1)
    forecast_features = poly.transform(forecast_elapsed_days)
    forecast_values = model.predict(forecast_features)

    _logger.info(
        "Linear regression forecast (degree=%d): %d historical "
        "point(s), %d period(s) projected.",
        degree,
        len(working),
        periods,
    )

    return ForecastResult(
        historical_dates=working[date_column],
        historical_values=working[value_column],
        forecast_dates=forecast_dates,
        forecast_values=pd.Series(np.asarray(forecast_values), index=forecast_dates),
        method="linear_regression",
    )
