# File: src/forecasting/exponential_smoothing.py
"""Holt-Winters exponential smoothing forecast, via statsmodels.

Fast, works well on short series, and handles trend and (optionally)
seasonality. The better default choice of this package's two methods
for a series without enough history to benefit from Prophet's more
elaborate seasonality decomposition — see
:mod:`~src.forecasting.prophet_forecast`'s own docstring for when that
method is the better fit instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.forecasting.forecast_input import validate_time_series

_logger = get_logger(__name__)

_VALID_TREND = {None, "add", "mul"}
_VALID_SEASONAL = {None, "add", "mul"}

# Below this many observations, a seasonal model has too few complete
# cycles to fit meaningfully even if the caller requests one —
# statsmodels itself will often raise on this case with a much less
# specific error, so this is caught here with a message naming the
# actual problem.
_MIN_OBSERVATIONS_FOR_SEASONAL = 10


@dataclass
class ForecastResult:
    """Result of a forecast.

    Attributes:
        historical_dates: The original series' dates, for plotting
            history alongside the projection.
        historical_values: The original series' values.
        forecast_dates: Projected future dates.
        forecast_values: Projected values for each date in
            ``forecast_dates``.
        method: Which forecasting method produced this result.
    """

    historical_dates: pd.Series
    historical_values: pd.Series
    forecast_dates: pd.DatetimeIndex
    forecast_values: pd.Series
    method: str


def forecast_exponential_smoothing(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
    periods: int,
    trend: str | None = "add",
    seasonal: str | None = None,
    seasonal_periods: int | None = None,
) -> ForecastResult:
    """Forecast ``periods`` steps ahead using Holt-Winters exponential smoothing.

    Args:
        dataframe: The source data.
        date_column: Column to use as the time axis.
        value_column: Numeric column to forecast.
        periods: How many future periods to project.
        trend: ``"add"`` (additive, default), ``"mul"``
            (multiplicative), or ``None`` (no trend component).
        seasonal: ``"add"``, ``"mul"``, or ``None`` (default — no
            seasonal component). If set, ``seasonal_periods`` is
            required.
        seasonal_periods: Length of one seasonal cycle (e.g. 12 for
            monthly data with yearly seasonality). Required if
            ``seasonal`` is set; ignored otherwise.

    Raises:
        ServiceError: If the underlying data fails
            :func:`~src.forecasting.forecast_input.validate_time_series`,
            ``periods`` is not positive, ``trend``/``seasonal`` are not
            recognized values, ``seasonal`` is set without
            ``seasonal_periods``, or there are too few observations for
            the requested seasonal period.
    """
    if periods <= 0:
        raise ServiceError(f"periods must be positive; got {periods}.")
    if trend not in _VALID_TREND:
        raise ServiceError(f"Invalid trend: {trend!r}. Must be 'add', 'mul', or None.")
    if seasonal not in _VALID_SEASONAL:
        raise ServiceError(
            f"Invalid seasonal: {seasonal!r}. Must be 'add', 'mul', or None."
        )
    if seasonal is not None and seasonal_periods is None:
        raise ServiceError("seasonal_periods is required when seasonal is set.")

    validated = validate_time_series(dataframe, date_column, value_column)
    working = validated.dataframe

    if seasonal is not None and len(working) < _MIN_OBSERVATIONS_FOR_SEASONAL:
        raise ServiceError(
            f"At least {_MIN_OBSERVATIONS_FOR_SEASONAL} observations "
            f"are required for a seasonal model; found {len(working)}. "
            f"Use seasonal=None for shorter series."
        )
    if seasonal is not None and len(working) < 2 * seasonal_periods:
        raise ServiceError(
            f"At least 2 full seasonal cycles ({2 * seasonal_periods} "
            f"observations) are required for seasonal_periods="
            f"{seasonal_periods}; found {len(working)}."
        )

    series = pd.Series(
        working[value_column].values,
        index=pd.DatetimeIndex(working[date_column]),
    )

    try:
        model = ExponentialSmoothing(
            series,
            trend=trend,
            seasonal=seasonal,
            seasonal_periods=seasonal_periods,
        ).fit()
    except Exception as exc:
        raise ServiceError(f"Failed to fit exponential smoothing model: {exc}") from exc

    forecast_values = model.forecast(periods)

    inferred_freq = pd.infer_freq(series.index) or "D"
    forecast_dates = pd.date_range(
        start=series.index[-1], periods=periods + 1, freq=inferred_freq
    )[1:]

    _logger.info(
        "Exponential smoothing forecast: %d historical point(s), %d "
        "period(s) projected, trend=%s, seasonal=%s.",
        len(working),
        periods,
        trend,
        seasonal,
    )

    return ForecastResult(
        historical_dates=working[date_column],
        historical_values=working[value_column],
        forecast_dates=forecast_dates,
        forecast_values=pd.Series(forecast_values.values, index=forecast_dates),
        method="exponential_smoothing",
    )
