# File: src/analysis/aggregation.py
"""Group-by aggregation: summarize numeric columns grouped by one or more categorical columns."""

from __future__ import annotations

import pandas as pd

from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)

_VALID_AGG_FUNCTIONS = {"sum", "mean", "median", "min", "max", "count", "std"}


def aggregate(
    dataframe: pd.DataFrame,
    group_by: list[str],
    agg_column: str,
    agg_function: str = "mean",
) -> pd.DataFrame:
    """Group ``dataframe`` by ``group_by`` and aggregate ``agg_column``.

    Args:
        dataframe: The dataframe to aggregate.
        group_by: One or more column names to group by.
        agg_column: The column to aggregate within each group.
        agg_function: One of ``"sum"``, ``"mean"``, ``"median"``,
            ``"min"``, ``"max"``, ``"count"``, ``"std"``.

    Returns:
        A dataframe with one row per unique combination of
        ``group_by`` values, indexed by those values, with a single
        column holding the aggregated result.

    Raises:
        ServiceError: If ``group_by`` is empty, any named column does
            not exist, ``agg_function`` is not recognized, or
            ``agg_function`` is a numeric-only operation (anything but
            ``"count"``) applied to a non-numeric ``agg_column``.
    """
    if not group_by:
        raise ServiceError("aggregate() requires at least one group_by column.")

    missing_group_cols = [c for c in group_by if c not in dataframe.columns]
    if missing_group_cols:
        raise ServiceError(
            f"group_by column(s) not found: {', '.join(missing_group_cols)}. "
            f"Available columns: {', '.join(str(c) for c in dataframe.columns)}."
        )

    if agg_column not in dataframe.columns:
        raise ServiceError(
            f"agg_column '{agg_column}' not found. Available columns: "
            f"{', '.join(str(c) for c in dataframe.columns)}."
        )

    if agg_function not in _VALID_AGG_FUNCTIONS:
        raise ServiceError(
            f"Invalid agg_function: {agg_function!r}. Must be one of "
            f"{', '.join(sorted(_VALID_AGG_FUNCTIONS))}."
        )

    if agg_function != "count" and not pd.api.types.is_numeric_dtype(
        dataframe[agg_column]
    ):
        raise ServiceError(
            f"agg_function '{agg_function}' requires a numeric column; "
            f"'{agg_column}' has dtype {dataframe[agg_column].dtype}. "
            f"Only 'count' is valid on non-numeric columns."
        )

    result = dataframe.groupby(group_by, dropna=False)[agg_column].agg(agg_function)
    result = result.to_frame(name=f"{agg_column}_{agg_function}")

    _logger.info(
        "Aggregated '%s' by %s using '%s': %d group(s).",
        agg_column,
        group_by,
        agg_function,
        len(result),
    )

    return result
