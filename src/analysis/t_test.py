# File: src/analysis/t_test.py
"""Independent-samples and paired-samples t-tests, via scipy.

Sits alongside :mod:`~src.analysis.correlation` as the same
plain-function-returning-a-dataclass shape, so both slot into
``tool_registry.py`` the same way. Two entry points rather than one
parameterized function — independent and paired t-tests take
genuinely different inputs (two independent columns/groups vs. two
paired columns of equal length) and conflating them behind one
``paired: bool`` flag would make the argument validation harder to
read than two short, separately-documented functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from scipy import stats

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)


@dataclass
class TTestResult:
    """Result of a t-test.

    Attributes:
        statistic: The t statistic.
        p_value: Two-sided p-value.
        degrees_of_freedom: Degrees of freedom used.
        group_a_mean: Mean of the first sample/group.
        group_b_mean: Mean of the second sample/group.
        test_type: ``"independent"`` or ``"paired"``.
        significant_at_0_05: Convenience flag — ``p_value < 0.05``.
    """

    statistic: float
    p_value: float
    degrees_of_freedom: float
    group_a_mean: float
    group_b_mean: float
    test_type: str
    significant_at_0_05: bool


def _require_numeric(dataframe: pd.DataFrame, column: str) -> None:
    if not pd.api.types.is_numeric_dtype(dataframe[column]):
        raise ServiceError(
            f"Column '{column}' must be numeric; has dtype {dataframe[column].dtype}."
        )


def independent_t_test(
    dataframe: pd.DataFrame,
    value_column: str,
    group_column: str,
    group_a: object,
    group_b: object,
    equal_variance: bool = False,
) -> TTestResult:
    """Compare ``value_column`` between two groups defined by ``group_column``.

    Args:
        dataframe: The source data.
        value_column: Numeric column being compared.
        group_column: Column whose values split rows into the two
            groups being compared.
        group_a: The value of ``group_column`` identifying the first
            group.
        group_b: The value of ``group_column`` identifying the second
            group.
        equal_variance: If ``True``, runs a standard Student's t-test
            (assumes equal population variance). Defaults to ``False``,
            running Welch's t-test instead — the safer default, since
            it does not assume equal variance and degrades to the
            standard test's result when variances genuinely are equal.

    Raises:
        ServiceError: If a named column does not exist, ``value_column``
            is not numeric, either group value is not present in
            ``group_column``, or either resulting group has fewer than
            2 observations (a t-test is not meaningful on a single
            point).
    """
    missing = [c for c in (value_column, group_column) if c not in dataframe.columns]
    if missing:
        raise ServiceError(
            f"Column(s) not found: {', '.join(missing)}. Available "
            f"columns: {', '.join(str(c) for c in dataframe.columns)}."
        )
    _require_numeric(dataframe, value_column)

    sample_a = dataframe.loc[dataframe[group_column] == group_a, value_column].dropna()
    sample_b = dataframe.loc[dataframe[group_column] == group_b, value_column].dropna()

    if len(sample_a) < 2 or len(sample_b) < 2:
        raise ServiceError(
            f"Each group needs at least 2 non-missing observations; "
            f"found {len(sample_a)} for {group_a!r} and {len(sample_b)} "
            f"for {group_b!r}."
        )

    result = stats.ttest_ind(sample_a, sample_b, equal_var=equal_variance)

    _logger.info(
        "Independent t-test on '%s' by '%s' (%r vs %r): t=%.4f, p=%.4f",
        value_column,
        group_column,
        group_a,
        group_b,
        result.statistic,
        result.pvalue,
    )

    return TTestResult(
        statistic=float(result.statistic),
        p_value=float(result.pvalue),
        degrees_of_freedom=float(result.df),
        group_a_mean=float(sample_a.mean()),
        group_b_mean=float(sample_b.mean()),
        test_type="independent",
        significant_at_0_05=bool(result.pvalue < 0.05),
    )


def paired_t_test(dataframe: pd.DataFrame, column_a: str, column_b: str) -> TTestResult:
    """Compare two paired numeric columns (e.g. before/after measurements on the same rows).

    Args:
        dataframe: The source data.
        column_a: First numeric column.
        column_b: Second numeric column, paired row-for-row with
            ``column_a``.

    Raises:
        ServiceError: If a named column does not exist, either is not
            numeric, or fewer than 2 rows have both values present
            (a paired test needs an actual pair to compare).
    """
    missing = [c for c in (column_a, column_b) if c not in dataframe.columns]
    if missing:
        raise ServiceError(
            f"Column(s) not found: {', '.join(missing)}. Available "
            f"columns: {', '.join(str(c) for c in dataframe.columns)}."
        )
    _require_numeric(dataframe, column_a)
    _require_numeric(dataframe, column_b)

    paired = dataframe[[column_a, column_b]].dropna()
    if len(paired) < 2:
        raise ServiceError(
            f"At least 2 rows with both '{column_a}' and '{column_b}' "
            f"present are required; found {len(paired)}."
        )

    result = stats.ttest_rel(paired[column_a], paired[column_b])

    _logger.info(
        "Paired t-test on '%s' vs '%s': t=%.4f, p=%.4f",
        column_a,
        column_b,
        result.statistic,
        result.pvalue,
    )

    return TTestResult(
        statistic=float(result.statistic),
        p_value=float(result.pvalue),
        degrees_of_freedom=float(len(paired) - 1),
        group_a_mean=float(paired[column_a].mean()),
        group_b_mean=float(paired[column_b].mean()),
        test_type="paired",
        significant_at_0_05=bool(result.pvalue < 0.05),
    )
