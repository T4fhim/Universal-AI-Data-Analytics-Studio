# File: src/analysis/crosstab.py
"""Cross-tabulation: frequency counts between two categorical columns."""

from __future__ import annotations

import pandas as pd

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)

_VALID_NORMALIZE_MODES = {None, "index", "columns", "all"}


def cross_tabulate(
    dataframe: pd.DataFrame,
    row_column: str,
    column_column: str,
    normalize: str | None = None,
) -> pd.DataFrame:
    """Build a frequency cross-tabulation of ``row_column`` against ``column_column``.

    Args:
        dataframe: The dataframe to analyze.
        row_column: Column whose values become row labels.
        column_column: Column whose values become column labels.
        normalize: If ``None`` (default), reports raw counts. If
            ``"index"``, each row sums to 1 (row-wise percentages). If
            ``"columns"``, each column sums to 1. If ``"all"``, the
            entire table sums to 1.

    Raises:
        ServiceError: If either column does not exist, they are the
            same column (a cross-tab of a column against itself is
            degenerate — always a diagonal matrix — and more likely a
            caller mistake than an intended request), or ``normalize``
            is not a recognized value.
    """
    if row_column not in dataframe.columns:
        raise ServiceError(
            f"row_column '{row_column}' not found. Available columns: "
            f"{', '.join(str(c) for c in dataframe.columns)}."
        )
    if column_column not in dataframe.columns:
        raise ServiceError(
            f"column_column '{column_column}' not found. Available "
            f"columns: {', '.join(str(c) for c in dataframe.columns)}."
        )
    if row_column == column_column:
        raise ServiceError(
            f"row_column and column_column are both '{row_column}'. "
            f"Cross-tabulating a column against itself always "
            f"produces a diagonal matrix; choose two different columns."
        )
    if normalize not in _VALID_NORMALIZE_MODES:
        raise ServiceError(
            f"Invalid normalize mode: {normalize!r}. Must be one of "
            f"None, 'index', 'columns', 'all'."
        )

    result = pd.crosstab(
        dataframe[row_column],
        dataframe[column_column],
        normalize=normalize if normalize is not None else False,
    )

    _logger.info(
        "Cross-tabulated '%s' x '%s': %d x %d table (normalize=%s).",
        row_column,
        column_column,
        result.shape[0],
        result.shape[1],
        normalize,
    )

    return result
