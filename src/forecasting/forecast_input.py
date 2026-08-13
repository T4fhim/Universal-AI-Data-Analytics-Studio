# File: src/forecasting/forecast_input.py
"""Shared time-series input validation for both forecasting methods.

Both :mod:`~src.forecasting.exponential_smoothing` and
:mod:`~src.forecasting.prophet_forecast` need a genuinely time-ordered
numeric series to produce a meaningful forecast — a forecast run
against an unsorted or unparseable date column would not error, it
would silently produce a nonsensical projection, which is a worse
failure mode than a loud rejection. This module is the one place that
validation lives, so both methods share the identical check rather
than risk two independently-written validators drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.core.exceptions import ServiceError


@dataclass
class ValidatedTimeSeries:
    """A dataframe confirmed safe to forecast on.

    Attributes:
        dataframe: A copy of the original data, with ``date_column``
            parsed to genuine datetime and sorted ascending.
        date_column: Name of the validated date column.
        value_column: Name of the validated numeric column.
    """

    dataframe: pd.DataFrame
    date_column: str
    value_column: str


def validate_time_series(
    dataframe: pd.DataFrame, date_column: str, value_column: str
) -> ValidatedTimeSeries:
    """Validate and prepare ``dataframe`` for forecasting.

    Args:
        dataframe: The source data.
        date_column: Column to use as the time axis.
        value_column: Numeric column to forecast.

    Raises:
        ServiceError: If either column does not exist, ``value_column``
            is not numeric, ``date_column`` cannot be parsed as dates
            (or contains any unparseable values), fewer than 3 valid
            rows remain after parsing (too few points for any
            meaningful trend), or the parsed dates contain duplicates
            (an ambiguous time axis — two rows claiming the same
            timestamp is not something either forecasting method can
            resolve on the caller's behalf).
    """
    missing = [c for c in (date_column, value_column) if c not in dataframe.columns]
    if missing:
        raise ServiceError(
            f"Column(s) not found: {', '.join(missing)}. Available "
            f"columns: {', '.join(str(c) for c in dataframe.columns)}."
        )

    if not pd.api.types.is_numeric_dtype(dataframe[value_column]):
        raise ServiceError(
            f"value_column '{value_column}' must be numeric; has "
            f"dtype {dataframe[value_column].dtype}."
        )

    working = dataframe[[date_column, value_column]].copy()

    parsed_dates = pd.to_datetime(working[date_column], errors="coerce")
    unparseable_count = int(parsed_dates.isna().sum() - working[date_column].isna().sum())
    if unparseable_count > 0:
        raise ServiceError(
            f"date_column '{date_column}' contains {unparseable_count} "
            f"value(s) that could not be parsed as dates. Every value "
            f"must be a valid date for forecasting."
        )

    working[date_column] = parsed_dates
    working = working.dropna(subset=[date_column, value_column])

    if len(working) < 3:
        raise ServiceError(
            f"At least 3 valid (date, value) pairs are required to "
            f"forecast; found {len(working)} after removing missing "
            f"values."
        )

    if working[date_column].duplicated().any():
        duplicate_count = int(working[date_column].duplicated().sum())
        raise ServiceError(
            f"date_column '{date_column}' contains {duplicate_count} "
            f"duplicate timestamp(s). Each row must have a unique "
            f"date to forecast against."
        )

    working = working.sort_values(date_column).reset_index(drop=True)

    return ValidatedTimeSeries(
        dataframe=working, date_column=date_column, value_column=value_column
    )
