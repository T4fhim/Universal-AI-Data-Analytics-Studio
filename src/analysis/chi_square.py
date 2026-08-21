# File: src/analysis/chi_square.py
"""Chi-square test of independence between two categorical columns, via scipy.

Reuses :func:`~src.analysis.crosstab.cross_tabulate`'s contingency
table for the same reason
:func:`~src.forecasting.model_comparison.compare_forecast_models`
reuses :mod:`~src.forecasting.forecast_input`: the contingency table
this test needs is exactly what ``cross_tabulate`` already builds and
validates, and re-deriving it here would risk the two drifting apart
on what counts as a valid pair of columns.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from scipy import stats

from src.analysis.crosstab import cross_tabulate
from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)


@dataclass
class ChiSquareResult:
    """Result of a chi-square test of independence.

    Attributes:
        statistic: The chi-square statistic.
        p_value: p-value for the null hypothesis that the two columns
            are independent.
        degrees_of_freedom: Degrees of freedom used.
        contingency_table: The observed-frequency contingency table
            (rows = ``row_column`` values, columns = ``column_column``
            values) the test was computed over — the same shape
            :func:`~src.analysis.crosstab.cross_tabulate` returns.
        significant_at_0_05: Convenience flag — ``p_value < 0.05``,
            i.e. evidence the two columns are *not* independent.
    """

    statistic: float
    p_value: float
    degrees_of_freedom: int
    contingency_table: pd.DataFrame
    significant_at_0_05: bool


def chi_square_test(
    dataframe: pd.DataFrame, row_column: str, column_column: str
) -> ChiSquareResult:
    """Test whether ``row_column`` and ``column_column`` are independent.

    Args:
        dataframe: The source data.
        row_column: First categorical column.
        column_column: Second categorical column.

    Raises:
        ServiceError: Propagated from
            :func:`~src.analysis.crosstab.cross_tabulate` if the
            columns don't exist or are the same column; raised
            directly here if the resulting contingency table has fewer
            than 2 categories on either axis (chi-square is undefined
            below a 2x2 table).
    """
    table = cross_tabulate(dataframe, row_column, column_column)

    if table.shape[0] < 2 or table.shape[1] < 2:
        raise ServiceError(
            f"Chi-square test requires at least 2 categories in each "
            f"of '{row_column}' and '{column_column}'; got a "
            f"{table.shape[0]}x{table.shape[1]} table."
        )

    chi2, p_value, dof, _expected = stats.chi2_contingency(table.values)

    _logger.info(
        "Chi-square test on '%s' vs '%s': chi2=%.4f, p=%.4f, dof=%d",
        row_column,
        column_column,
        chi2,
        p_value,
        dof,
    )

    return ChiSquareResult(
        statistic=float(chi2),
        p_value=float(p_value),
        degrees_of_freedom=int(dof),
        contingency_table=table,
        significant_at_0_05=bool(p_value < 0.05),
    )
