# File: src/forecasting/prophet_forecast.py
"""Prophet-based forecast.

Better than :mod:`~src.forecasting.exponential_smoothing` for longer
series with multiple seasonal patterns (e.g. both weekly and yearly
cycles) and series with missing dates or outliers, which Prophet is
built to tolerate. Heavier and slower to fit — for a short series with
one simple seasonal pattern, exponential smoothing is usually the
better default (see that module's own docstring).

Prophet's own API requires columns literally named ``ds`` (date) and
``y`` (value) — confirmed directly against a real fit before writing
this wrapper, not assumed from documentation. This module renames the
caller's actual column names to and from Prophet's required names, so
callers of this function never need to know about that constraint.
"""

from __future__ import annotations

import logging

import pandas as pd
from prophet import Prophet

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.forecasting.exponential_smoothing import ForecastResult
from src.forecasting.forecast_input import validate_time_series

_logger = get_logger(__name__)

# Prophet and its underlying cmdstanpy dependency are verbose at INFO
# level by default (fit-progress messages) — silenced here so a
# forecast call does not flood this project's own logging output with
# a third-party library's internal progress chatter unrelated to
# anything this application's own log levels are meant to control.
logging.getLogger("prophet").setLevel(logging.WARNING)
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)


def forecast_prophet(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
    periods: int,
    include_confidence_interval: bool = True,
) -> ForecastResult:
    """Forecast ``periods`` steps ahead using Prophet.

    Args:
        dataframe: The source data.
        date_column: Column to use as the time axis.
        value_column: Numeric column to forecast.
        periods: How many future periods to project.
        include_confidence_interval: If ``True`` (default), the
            returned :class:`~src.forecasting.exponential_smoothing.
            ForecastResult`'s ``forecast_values`` carries
            ``lower``/``upper`` bounds as a DataFrame instead of a
            plain Series — a genuine capability
            :mod:`~src.forecasting.exponential_smoothing` does not
            provide, exposed here rather than dropped to match that
            method's simpler shape.

    Raises:
        ServiceError: If the underlying data fails
            :func:`~src.forecasting.forecast_input.validate_time_series`,
            ``periods`` is not positive, or Prophet's own fit fails
            (extremely short or degenerate series can trigger this).
    """
    if periods <= 0:
        raise ServiceError(f"periods must be positive; got {periods}.")

    validated = validate_time_series(dataframe, date_column, value_column)
    working = validated.dataframe

    prophet_input = pd.DataFrame(
        {"ds": working[date_column], "y": working[value_column]}
    )

    try:
        model = Prophet()
        model.fit(prophet_input)
    except Exception as exc:
        raise ServiceError(f"Failed to fit Prophet model: {exc}") from exc

    future = model.make_future_dataframe(periods=periods)
    forecast = model.predict(future)

    future_only = forecast.tail(periods)

    if include_confidence_interval:
        forecast_values = pd.DataFrame(
            {
                "yhat": future_only["yhat"].values,
                "lower": future_only["yhat_lower"].values,
                "upper": future_only["yhat_upper"].values,
            },
            index=pd.DatetimeIndex(future_only["ds"]),
        )
    else:
        forecast_values = pd.Series(
            future_only["yhat"].values, index=pd.DatetimeIndex(future_only["ds"])
        )

    _logger.info(
        "Prophet forecast: %d historical point(s), %d period(s) projected.",
        len(working),
        periods,
    )

    return ForecastResult(
        historical_dates=working[date_column],
        historical_values=working[value_column],
        forecast_dates=pd.DatetimeIndex(future_only["ds"]),
        forecast_values=forecast_values,
        method="prophet",
    )
