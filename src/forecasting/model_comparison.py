# File: src/forecasting/model_comparison.py
"""Runs every applicable forecasting model on the same series and ranks them (milestone 9).

Backs the orchestrator's "Automatic Model Competition": rather than the
user (or the AI) guessing which of :func:`~src.forecasting.
exponential_smoothing.forecast_exponential_smoothing` or
:func:`~src.forecasting.prophet_forecast.forecast_prophet` fits a given
series better, this module fits both against a held-out tail of the
series, scores each by how well it predicted the values it didn't see,
and ranks accordingly — the same evaluation methodology
(train/holdout split, then MAPE/RMSE against the held-out actuals) a
human analyst would use, not a heuristic guess based on series shape.

Every candidate model's *real* forecast (the one actually returned to
the caller as ``ForecastResult``) is still fit on the **full** series —
the holdout split exists only to score which model to trust, not to
throw away the most recent data from the forecast that ships.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable

import pandas as pd

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.forecasting.arima_forecast import forecast_arima
from src.forecasting.exponential_smoothing import (
    ForecastResult,
    forecast_exponential_smoothing,
)
from src.forecasting.forecast_input import validate_time_series
from src.forecasting.linear_regression_forecast import forecast_linear_regression
from src.forecasting.prophet_forecast import forecast_prophet
from src.forecasting.random_forest_forecast import forecast_random_forest

_logger = get_logger(__name__)

# Each candidate: a name and a (dataframe, date_column, value_column,
# periods) -> ForecastResult callable with every other parameter
# defaulted, matching how src.ai.tool_registry's forecast tools also
# call these two functions with defaults — model comparison and the
# AI-driven single-model tools stay consistent about what "the
# exponential smoothing model" means with no extra configuration.
_CANDIDATE_FORECASTERS: list[
    tuple[str, Callable[[pd.DataFrame, str, str, int], ForecastResult]]
] = [
    (
        "exponential_smoothing",
        lambda df, date_col, value_col, periods: forecast_exponential_smoothing(
            df, date_col, value_col, periods
        ),
    ),
    (
        "prophet",
        lambda df, date_col, value_col, periods: forecast_prophet(
            df, date_col, value_col, periods, include_confidence_interval=False
        ),
    ),
    (
        "linear_regression",
        lambda df, date_col, value_col, periods: forecast_linear_regression(
            df, date_col, value_col, periods
        ),
    ),
    (
        "arima",
        lambda df, date_col, value_col, periods: forecast_arima(
            df, date_col, value_col, periods
        ),
    ),
    (
        "random_forest",
        lambda df, date_col, value_col, periods: forecast_random_forest(
            df, date_col, value_col, periods
        ),
    ),
]

# A holdout smaller than this leaves too few points to compute a
# stable error metric from — an exact mirror of forecast_input.py's
# own "3 point minimum" reasoning, applied to the evaluation split
# rather than the whole series.
_MIN_HOLDOUT_PERIODS = 2


@dataclass
class ModelCandidateResult:
    """One forecasting method's result and holdout-evaluated accuracy.

    Attributes:
        method: Matches :attr:`~src.forecasting.exponential_smoothing.
            ForecastResult.method` on ``result``.
        mape: Mean Absolute Percentage Error against the held-out
            actuals, as a percentage (lower is better). ``None`` if it
            could not be computed (every held-out actual was exactly
            zero, making percentage error undefined).
        rmse: Root Mean Squared Error against the held-out actuals, in
            the series' own units (lower is better). Always computable
            (unlike MAPE, division by the actual value is not involved).
        result: The model refit on the **full** series — this is the
            real forecast to use, not the holdout-evaluation fit.
    """

    method: str
    mape: float | None
    rmse: float
    result: ForecastResult


@dataclass
class ModelComparisonResult:
    """Ranked outcome of :func:`compare_forecast_models`.

    Attributes:
        candidates: Every model that could be fit, sorted best first.
            Ranked by MAPE when available (the more interpretable,
            scale-independent metric); candidates whose MAPE is
            ``None`` sort after every candidate with a real MAPE,
            ordered by RMSE among themselves.
        winner: ``candidates[0]`` — kept as a separate named attribute
            so a caller that only wants "the best model's forecast"
            doesn't need to index into the list.
    """

    candidates: list[ModelCandidateResult]
    winner: ModelCandidateResult


def _forecast_values_as_series(result: ForecastResult) -> pd.Series:
    """Normalize ``ForecastResult.forecast_values`` to a plain Series of point estimates.

    Prophet's result (when ``include_confidence_interval=True``) is a
    DataFrame with ``yhat``/``lower``/``upper`` columns (see
    ``prophet_forecast.py``'s own docstring) — this module always calls
    it with ``include_confidence_interval=False`` precisely so this
    normalization is never needed for the candidates it fits itself,
    but this helper stays defensive in case a future caller passes in
    a ``ForecastResult`` built with intervals.
    """
    if isinstance(result.forecast_values, pd.DataFrame):
        return result.forecast_values["yhat"]
    return result.forecast_values


def compare_forecast_models(
    dataframe: pd.DataFrame,
    date_column: str,
    value_column: str,
    periods: int,
    holdout_periods: int | None = None,
) -> ModelComparisonResult:
    """Fit every candidate forecasting model and rank them by holdout accuracy.

    Args:
        dataframe: The source data.
        date_column: Column to use as the time axis.
        value_column: Numeric column to forecast.
        periods: How many future periods the winning (and every other
            candidate's) real forecast should project.
        holdout_periods: How many of the series' most recent points to
            hold out for scoring. Defaults to 20% of the series
            (rounded down, minimum :data:`_MIN_HOLDOUT_PERIODS`) when
            not given — an arbitrary but standard train/test split
            ratio for a series too short to justify a more elaborate
            cross-validation scheme.

    Raises:
        ServiceError: If the series fails
            :func:`~src.forecasting.forecast_input.validate_time_series`,
            there are too few points to reserve a holdout of at least
            :data:`_MIN_HOLDOUT_PERIODS` while leaving 3+ training
            points, or every candidate model failed to fit (each
            individual failure is logged and skipped rather than
            raised, so one method's failure doesn't block a working
            alternative from being reported).
    """
    validated = validate_time_series(dataframe, date_column, value_column)
    working = validated.dataframe

    if holdout_periods is None:
        holdout_periods = max(_MIN_HOLDOUT_PERIODS, len(working) // 5)

    if holdout_periods < _MIN_HOLDOUT_PERIODS:
        raise ServiceError(
            f"holdout_periods must be at least {_MIN_HOLDOUT_PERIODS}; got {holdout_periods}."
        )
    if len(working) - holdout_periods < 3:
        raise ServiceError(
            f"Series has {len(working)} point(s); reserving a "
            f"{holdout_periods}-point holdout would leave fewer than "
            f"the 3 required to fit a model. Use a shorter "
            f"holdout_periods or supply more data."
        )

    train = working.iloc[:-holdout_periods]
    holdout_actual = working.iloc[-holdout_periods:][value_column].reset_index(
        drop=True
    )

    candidates: list[ModelCandidateResult] = []
    for method_name, forecaster in _CANDIDATE_FORECASTERS:
        try:
            holdout_forecast = forecaster(
                train, date_column, value_column, holdout_periods
            )
        except ServiceError as exc:
            _logger.warning(
                "Model comparison: '%s' failed to fit on the holdout split, skipped: %s",
                method_name,
                exc,
            )
            continue

        predicted = _forecast_values_as_series(holdout_forecast).reset_index(drop=True)
        errors = holdout_actual - predicted
        rmse = float((errors**2).mean() ** 0.5)

        nonzero_mask = holdout_actual != 0
        if nonzero_mask.any():
            percentage_errors = (
                errors[nonzero_mask] / holdout_actual[nonzero_mask]
            ).abs()
            mape = float(percentage_errors.mean() * 100)
        else:
            mape = None  # every held-out actual was zero; percentage error is undefined

        try:
            full_result = forecaster(working, date_column, value_column, periods)
        except ServiceError as exc:
            _logger.warning(
                "Model comparison: '%s' fit the holdout split but failed "
                "on the full series, skipped: %s",
                method_name,
                exc,
            )
            continue

        candidates.append(
            ModelCandidateResult(
                method=method_name, mape=mape, rmse=rmse, result=full_result
            )
        )

    if not candidates:
        raise ServiceError(
            "No forecasting model could be fit for this series — every "
            "candidate failed. See the log for each model's specific error."
        )

    candidates.sort(
        key=lambda c: (c.mape is None, c.mape if c.mape is not None else 0.0, c.rmse)
    )

    _logger.info(
        "Model comparison: %d candidate(s) evaluated, winner=%s (MAPE=%s, RMSE=%.4f).",
        len(candidates),
        candidates[0].method,
        f"{candidates[0].mape:.2f}%" if candidates[0].mape is not None else "n/a",
        candidates[0].rmse,
    )

    return ModelComparisonResult(candidates=candidates, winner=candidates[0])
