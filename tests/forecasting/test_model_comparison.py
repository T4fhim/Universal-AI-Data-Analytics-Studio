# File: tests/forecasting/test_model_comparison.py
"""Tests for src.forecasting.model_comparison.compare_forecast_models.

Uses a real (small, synthetic) time series rather than mocking either
forecasting method — the whole point of this module is genuine
holdout-accuracy comparison, so a test that mocked forecast_* would
verify nothing about whether the comparison itself is correct.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.core.exceptions import ServiceError
from src.forecasting.model_comparison import compare_forecast_models


def _trending_series(n: int = 40) -> pd.DataFrame:
    dates = pd.date_range("2023-01-01", periods=n, freq="D")
    values = 10 + np.arange(n) * 0.5 + np.sin(np.arange(n) / 3) * 2
    return pd.DataFrame({"date": dates, "value": values})


def test_compare_forecast_models_returns_ranked_candidates() -> None:
    result = compare_forecast_models(_trending_series(), "date", "value", periods=5)

    assert len(result.candidates) >= 1
    assert result.winner is result.candidates[0]
    # Sorted best-first: each candidate's MAPE (when present) is >= the previous.
    mapes = [c.mape for c in result.candidates if c.mape is not None]
    assert mapes == sorted(mapes)


def test_compare_forecast_models_winner_forecast_has_requested_periods() -> None:
    result = compare_forecast_models(_trending_series(), "date", "value", periods=7)

    assert len(result.winner.result.forecast_values) == 7
    # Milestone 11 expanded the candidate set beyond the original two —
    # any registered candidate is a legitimate winner now.
    assert result.winner.result.method in {
        "exponential_smoothing",
        "prophet",
        "linear_regression",
        "arima",
        "random_forest",
    }


def test_compare_forecast_models_rmse_always_present_mape_may_be_none() -> None:
    result = compare_forecast_models(_trending_series(), "date", "value", periods=5)

    for candidate in result.candidates:
        assert candidate.rmse >= 0.0
        assert candidate.mape is None or candidate.mape >= 0.0


def test_compare_forecast_models_rejects_holdout_too_small() -> None:
    with pytest.raises(ServiceError, match="at least 2"):
        compare_forecast_models(
            _trending_series(), "date", "value", periods=5, holdout_periods=1
        )


def test_compare_forecast_models_rejects_series_too_short_for_requested_holdout() -> (
    None
):
    short_series = _trending_series(n=6)
    with pytest.raises(ServiceError, match="fewer than the 3 required"):
        compare_forecast_models(
            short_series, "date", "value", periods=2, holdout_periods=4
        )


def test_compare_forecast_models_propagates_underlying_validation_error() -> None:
    # Reuses forecast_input.validate_time_series's own validation (a
    # non-numeric value_column) — model_comparison must not swallow it.
    bad = pd.DataFrame(
        {"date": pd.date_range("2023-01-01", periods=10), "value": ["a"] * 10}
    )
    with pytest.raises(ServiceError, match="must be numeric"):
        compare_forecast_models(bad, "date", "value", periods=2)


def test_compare_forecast_models_default_holdout_is_reasonable_fraction() -> None:
    # 40 points, no explicit holdout_periods -> should use max(2, 40//5)=8,
    # leaving 32 training points — well above the 3-point minimum, so this
    # should succeed without the caller needing to reason about the split.
    result = compare_forecast_models(_trending_series(n=40), "date", "value", periods=5)
    assert result.winner is not None


# -- progress_callback (milestone 25) --------------------------------------------------------


def test_compare_forecast_models_reports_progress_once_per_candidate() -> None:
    """Milestone 25's own new parameter — the first genuinely slow src.forecasting operation
    reports incremental progress, matching WorkerSignals.progress's (int, str) contract exactly
    (see that class's own docstring) so a caller can hand this straight to WorkerRunner.
    """
    events: list[tuple[int, str]] = []

    result = compare_forecast_models(
        _trending_series(),
        "date",
        "value",
        periods=5,
        progress_callback=lambda percent, message: events.append((percent, message)),
    )

    # One 0% "starting" event, plus one event per registered candidate forecaster.
    assert events[0] == (0, "Starting model comparison…")
    assert len(events) == 1 + len(_CANDIDATE_FORECASTER_NAMES)
    # Percentages are monotonically non-decreasing and the final one reaches 100.
    percentages = [percent for percent, _message in events]
    assert percentages == sorted(percentages)
    assert percentages[-1] == 100
    # Every candidate's name appears in some progress message.
    for name in _CANDIDATE_FORECASTER_NAMES:
        assert any(name.replace("_", " ") in message for _percent, message in events)
    assert (
        len(result.candidates) >= 1
    )  # the callback did not interfere with the real result


def test_compare_forecast_models_with_no_progress_callback_is_unaffected() -> None:
    # Every pre-existing call site omits progress_callback -- must remain a true no-op.
    result = compare_forecast_models(_trending_series(), "date", "value", periods=5)
    assert result.winner is not None


_CANDIDATE_FORECASTER_NAMES = (
    "exponential_smoothing",
    "prophet",
    "linear_regression",
    "arima",
    "random_forest",
)
