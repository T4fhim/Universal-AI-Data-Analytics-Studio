# File: src/analysis/correlation.py
"""Correlation matrix for numeric columns, excluding ambiguous-type columns.

Reuses :func:`~src.readers.type_inference.find_ambiguous_type_columns`
for the same reason :mod:`~src.analysis.dataset_profile` does — a
column flagged ambiguous is not genuinely numeric even if pandas'
dtype inference happens to be numeric-compatible in places, and
including it would produce a correlation coefficient over data the
column's own profile already says should not be trusted numerically.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.readers.type_inference import find_ambiguous_type_columns

_logger = get_logger(__name__)

_VALID_METHODS = {"pearson", "spearman", "kendall"}


@dataclass
class CorrelationResult:
    """Result of a correlation computation.

    Attributes:
        matrix: The correlation matrix itself.
        included_columns: Numeric columns that were included.
        excluded_columns: Columns excluded because they were
            ambiguous-type or non-numeric, with the reason for each.
        method: Which correlation method was used.
    """

    matrix: pd.DataFrame
    included_columns: list[str]
    excluded_columns: dict[str, str]
    method: str


def compute_correlation(
    dataframe: pd.DataFrame, method: str = "pearson"
) -> CorrelationResult:
    """Compute a correlation matrix over ``dataframe``'s genuinely numeric columns.

    Args:
        dataframe: The dataframe to analyze.
        method: One of ``"pearson"`` (linear correlation, the
            default), ``"spearman"`` (rank correlation, more robust to
            outliers and non-linear monotonic relationships), or
            ``"kendall"`` (rank correlation, more robust than Spearman
            on small samples but more expensive to compute).

    Raises:
        ServiceError: If ``method`` is not recognized, or if fewer
            than 2 genuinely numeric columns are available (a
            correlation matrix over 0 or 1 columns is not meaningful).
    """
    if method not in _VALID_METHODS:
        raise ServiceError(
            f"Invalid correlation method: {method!r}. Must be one of "
            f"{', '.join(sorted(_VALID_METHODS))}."
        )

    ambiguous_columns = find_ambiguous_type_columns(dataframe)

    included_columns = []
    excluded_columns: dict[str, str] = {}

    for column_name in dataframe.columns:
        if column_name in ambiguous_columns:
            excluded_columns[str(column_name)] = "ambiguous type (mixed numeric/text)"
        elif pd.api.types.is_numeric_dtype(dataframe[column_name]):
            included_columns.append(column_name)
        else:
            excluded_columns[str(column_name)] = "not numeric"

    if len(included_columns) < 2:
        raise ServiceError(
            f"Correlation requires at least 2 genuinely numeric "
            f"columns; found {len(included_columns)} "
            f"({', '.join(str(c) for c in included_columns)}). "
            f"Excluded: "
            f"{', '.join(f'{k} ({v})' for k, v in excluded_columns.items())}."
        )

    matrix = dataframe[included_columns].corr(method=method)

    _logger.info(
        "Computed %s correlation over %d column(s), excluded %d.",
        method,
        len(included_columns),
        len(excluded_columns),
    )

    return CorrelationResult(
        matrix=matrix,
        included_columns=[str(c) for c in included_columns],
        excluded_columns=excluded_columns,
        method=method,
    )
