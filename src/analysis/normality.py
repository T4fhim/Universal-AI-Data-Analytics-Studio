# File: src/analysis/normality.py
"""Normality tests (Shapiro-Wilk, D'Agostino-Pearson) for a single numeric column.

Exists as its own module rather than folded into
:mod:`~src.analysis.t_test`/:mod:`~src.analysis.anova` because
normality is a precondition check consumers run *before* deciding
which test to use (a parametric test like ``independent_t_test`` vs. a
distribution-free alternative), not a step inside either of those
tests themselves — the same reasoning that keeps
:mod:`~src.forecasting.forecast_input`'s validation separate from the
forecasting methods that consume it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from scipy import stats

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)

# Below this many observations, D'Agostino-Pearson's underlying
# skewness/kurtosis tests are unreliable (scipy itself warns below 8;
# a slightly higher floor is used here since a warning-level result is
# not useful to surface as though it were a trustworthy answer).
_MIN_OBSERVATIONS_DAGOSTINO = 8

# Shapiro-Wilk's own documented reliable range tops out around 5000
# observations in scipy's implementation; beyond that the p-value
# becomes overly sensitive to trivial deviations rather than
# meaningfully informative, so this is reported as a known limitation
# rather than silently returning a misleading result.
_MAX_OBSERVATIONS_SHAPIRO = 5000


@dataclass
class NormalityResult:
    """Result of a normality test.

    Attributes:
        method: ``"shapiro_wilk"`` or ``"dagostino_pearson"``.
        statistic: The test statistic.
        p_value: p-value for the null hypothesis that the data is
            normally distributed.
        appears_normal_at_0_05: Convenience flag — ``p_value >= 0.05``
            (fails to reject normality at the 5% level; note this is
            evidence *for*, not proof *of*, normality).
        observation_count: Number of non-missing values tested.
    """

    method: str
    statistic: float
    p_value: float
    appears_normal_at_0_05: bool
    observation_count: int


def check_normality(
    dataframe: pd.DataFrame, column: str, method: str = "shapiro_wilk"
) -> NormalityResult:
    """Test whether ``column``'s values appear normally distributed.

    Args:
        dataframe: The source data.
        column: Numeric column to test.
        method: ``"shapiro_wilk"`` (default — generally the more
            powerful choice for small-to-moderate samples) or
            ``"dagostino_pearson"`` (based on skewness and kurtosis;
            a reasonable alternative for larger samples where
            Shapiro-Wilk's reliable range is exceeded).

    Raises:
        ServiceError: If ``column`` does not exist, is not numeric,
            ``method`` is not recognized, there are fewer than 3
            non-missing values, or ``method="shapiro_wilk"`` is
            requested with more than 5000 observations (use
            ``"dagostino_pearson"`` instead at that scale).
    """
    if column not in dataframe.columns:
        raise ServiceError(
            f"Column '{column}' not found. Available columns: "
            f"{', '.join(str(c) for c in dataframe.columns)}."
        )
    if not pd.api.types.is_numeric_dtype(dataframe[column]):
        raise ServiceError(
            f"Column '{column}' must be numeric; has dtype {dataframe[column].dtype}."
        )
    if method not in {"shapiro_wilk", "dagostino_pearson"}:
        raise ServiceError(
            f"Invalid method: {method!r}. Must be 'shapiro_wilk' or "
            f"'dagostino_pearson'."
        )

    values = dataframe[column].dropna()
    if len(values) < 3:
        raise ServiceError(
            f"At least 3 non-missing values are required to test "
            f"normality; found {len(values)}."
        )

    if method == "shapiro_wilk":
        if len(values) > _MAX_OBSERVATIONS_SHAPIRO:
            raise ServiceError(
                f"Shapiro-Wilk is only reliable up to "
                f"{_MAX_OBSERVATIONS_SHAPIRO} observations; found "
                f"{len(values)}. Use method='dagostino_pearson' instead."
            )
        statistic, p_value = stats.shapiro(values)
    else:
        if len(values) < _MIN_OBSERVATIONS_DAGOSTINO:
            raise ServiceError(
                f"D'Agostino-Pearson requires at least "
                f"{_MIN_OBSERVATIONS_DAGOSTINO} observations for a "
                f"reliable result; found {len(values)}. Use "
                f"method='shapiro_wilk' for smaller samples."
            )
        statistic, p_value = stats.normaltest(values)

    _logger.info(
        "Normality test (%s) on '%s' (%d observations): statistic=%.4f, p=%.4f",
        method,
        column,
        len(values),
        statistic,
        p_value,
    )

    return NormalityResult(
        method=method,
        statistic=float(statistic),
        p_value=float(p_value),
        appears_normal_at_0_05=bool(p_value >= 0.05),
        observation_count=len(values),
    )
