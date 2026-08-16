# File: src/analysis/anova.py
"""One-way ANOVA (analysis of variance) across 3+ groups, via scipy.

Complements :mod:`~src.analysis.t_test`: a t-test compares exactly two
groups; ANOVA is the equivalent test when a categorical column splits
the data into three or more groups being compared on one numeric
measure at once, rather than running repeated pairwise t-tests (which
would inflate the false-positive rate — the reason ANOVA exists as its
own test rather than "just run several t-tests").
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from scipy import stats

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)

_MIN_GROUPS = 3
_MIN_OBSERVATIONS_PER_GROUP = 2


@dataclass
class AnovaResult:
    """Result of a one-way ANOVA.

    Attributes:
        f_statistic: The F statistic.
        p_value: p-value for the null hypothesis that all group means
            are equal.
        group_means: Mean of ``value_column`` per group.
        group_sizes: Observation count per group.
        significant_at_0_05: Convenience flag — ``p_value < 0.05``.
    """

    f_statistic: float
    p_value: float
    group_means: dict[str, float]
    group_sizes: dict[str, int]
    significant_at_0_05: bool


def one_way_anova(
    dataframe: pd.DataFrame, value_column: str, group_column: str
) -> AnovaResult:
    """Test whether ``value_column``'s mean differs across the groups in ``group_column``.

    Args:
        dataframe: The source data.
        value_column: Numeric column being compared across groups.
        group_column: Categorical column defining the groups.

    Raises:
        ServiceError: If a named column does not exist, ``value_column``
            is not numeric, fewer than 3 distinct groups remain after
            dropping missing values (below 3 groups, use
            :func:`~src.analysis.t_test.independent_t_test` instead),
            or any group has fewer than 2 observations.
    """
    missing = [c for c in (value_column, group_column) if c not in dataframe.columns]
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

    working = dataframe[[value_column, group_column]].dropna()
    groups = {
        str(name): sub[value_column]
        for name, sub in working.groupby(group_column, sort=False)
    }

    if len(groups) < _MIN_GROUPS:
        raise ServiceError(
            f"One-way ANOVA requires at least {_MIN_GROUPS} distinct "
            f"groups in '{group_column}'; found {len(groups)}. Use "
            f"independent_t_test for exactly 2 groups."
        )

    too_small = {
        name: len(s)
        for name, s in groups.items()
        if len(s) < _MIN_OBSERVATIONS_PER_GROUP
    }
    if too_small:
        raise ServiceError(
            f"Every group needs at least {_MIN_OBSERVATIONS_PER_GROUP} "
            f"observations; too few in: "
            f"{', '.join(f'{k} ({v})' for k, v in too_small.items())}."
        )

    result = stats.f_oneway(*groups.values())

    _logger.info(
        "One-way ANOVA on '%s' by '%s' (%d groups): F=%.4f, p=%.4f",
        value_column,
        group_column,
        len(groups),
        result.statistic,
        result.pvalue,
    )

    return AnovaResult(
        f_statistic=float(result.statistic),
        p_value=float(result.pvalue),
        group_means={name: float(s.mean()) for name, s in groups.items()},
        group_sizes={name: len(s) for name, s in groups.items()},
        significant_at_0_05=bool(result.pvalue < 0.05),
    )
