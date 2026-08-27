# File: src/forecasting/arima_forecast.py
"""ARIMA/SARIMA forecast, via pmdarima's auto_arima over statsmodels.

Uses ``pmdarima.auto_arima`` rather than requiring the caller to
specify ``(p, d, q)`` orders directly — this project's other
forecasters (:mod:`~src.forecasting.exponential_smoothing`,
:mod:`~src.forecasting.prophet_forecast`) also avoid asking the AI
assistant or an end user to supply low-level model hyperparameters
they are unlikely to know how to choose; auto_arima searches the order
space itself via stepwise AIC minimization, matching that same
"reasonable defaults, no required tuning" shape.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pmdarima as pm

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.forecasting.exponential_smoothing import ForecastResult
from src.forecasting.forecast_input import validate_time_series

_logger = get_logger(__name__)

# Below this many observations, auto_arima's stepwise search has too
# little data to reliably distinguish candidate orders — it will often
# either raise or silently settle on a degenerate (0,0,0) model that
# is really just the series mean, which is not a useful forecast to
# present as "ARIMA" to a user or the AI assistant.
_MIN_OBSERVATIONS = 10


def forecast_arima(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
    periods: int,
    seasonal: bool = False,
    seasonal_periods: int | None = None,
) -> ForecastResult:
    """Forecast ``periods`` steps ahead using an auto-selected ARIMA/SARIMA model.

    Args:
        dataframe: The source data.
        date_column: Column to use as the time axis.
        value_column: Numeric column to forecast.
        periods: How many future periods to project.
        seasonal: If ``True``, fits a seasonal ARIMA (SARIMA) model
            instead of plain ARIMA. Requires ``seasonal_periods``.
        seasonal_periods: Length of one seasonal cycle (e.g. 12 for
            monthly data with yearly seasonality). Required if
            ``seasonal`` is ``True``; ignored otherwise.

    Raises:
        ServiceError: If the underlying data fails
            :func:`~src.forecasting.forecast_input.validate_time_series`,
            ``periods`` is not positive, ``seasonal`` is ``True``
            without ``seasonal_periods``, there are fewer than 10
            observations, or auto_arima fails to fit any candidate
            model.
    """
    if periods <= 0:
        raise ServiceError(f"periods must be positive; got {periods}.")
    if seasonal and seasonal_periods is None:
        raise ServiceError("seasonal_periods is required when seasonal=True.")

    validated = validate_time_series(dataframe, date_column, value_column)
    working = validated.dataframe

    if len(working) < _MIN_OBSERVATIONS:
        raise ServiceError(
            f"At least {_MIN_OBSERVATIONS} observations are required "
            f"to fit an ARIMA model; found {len(working)}."
        )

    series = working[value_column].to_numpy()

    try:
        model = pm.auto_arima(
            series,
            seasonal=seasonal,
            m=seasonal_periods if seasonal else 1,
            suppress_warnings=True,
            error_action="raise",
        )
    except Exception as exc:
        raise ServiceError(f"Failed to fit ARIMA model: {exc}") from exc

    forecast_values = model.predict(n_periods=periods)

    dates = pd.DatetimeIndex(working[date_column])
    inferred_freq = pd.infer_freq(dates) or "D"
    forecast_dates = pd.date_range(
        start=dates[-1], periods=periods + 1, freq=inferred_freq
    )[1:]

    method_name = "sarima" if seasonal else "arima"
    _logger.info(
        "%s forecast: %d historical point(s), %d period(s) projected, order=%s.",
        method_name.upper(),
        len(working),
        periods,
        model.order,
    )

    return ForecastResult(
        historical_dates=working[date_column],
        historical_values=working[value_column],
        forecast_dates=forecast_dates,
        forecast_values=pd.Series(np.asarray(forecast_values), index=forecast_dates),
        method=method_name,
    )
