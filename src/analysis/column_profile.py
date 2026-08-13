# File: src/analysis/column_profile.py
"""Per-column profiling: type, missingness, uniqueness, and type-appropriate statistics.

:func:`profile_column` reuses
:func:`~src.readers.type_inference.find_ambiguous_type_columns` rather
than re-deriving the same "mixed type" signal independently — that
function's own docstring documents two rounds of real bugs found
getting this detection right against this project's actual pandas
version; duplicating that logic here would risk reintroducing either
bug rather than reusing the already-verified fix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.core.logger import get_logger
from src.readers.type_inference import find_ambiguous_type_columns

_logger = get_logger(__name__)

# Number of most-frequent values to report for text/categorical
# columns — enough to show a real distribution shape, not so many
# that a high-cardinality column produces an unreadable report.
_TOP_VALUES_COUNT = 5


@dataclass
class ColumnProfile:
    """Profile of a single column.

    Attributes:
        name: Column name.
        dtype: The column's pandas dtype, as a string.
        missing_count: Number of missing (NaN/None) values.
        missing_percentage: ``missing_count`` as a percentage of total
            rows, rounded to 1 decimal place.
        unique_count: Number of distinct non-missing values.
        is_ambiguous_type: Whether this column was flagged by
            :func:`~src.readers.type_inference.
            find_ambiguous_type_columns` — a mix of numeric and
            non-numeric values under a text dtype.
        numeric_stats: Populated only for numeric columns:
            ``{"min", "max", "mean", "median", "std"}``. ``None`` for
            non-numeric columns.
        top_values: Populated only for non-numeric columns: the
            :data:`_TOP_VALUES_COUNT` most frequent values with their
            counts, as ``[(value, count), ...]``. ``None`` for numeric
            columns — a numeric column's "most frequent value" is
            rarely meaningful the way a category's is, and
            ``numeric_stats`` already covers the numeric case.
        datetime_range: Populated only for datetime columns:
            ``(min, max)``. ``None`` otherwise.
    """

    name: str
    dtype: str
    missing_count: int
    missing_percentage: float
    unique_count: int
    is_ambiguous_type: bool
    numeric_stats: dict[str, float] | None = None
    top_values: list[tuple[Any, int]] | None = None
    datetime_range: tuple[Any, Any] | None = None


def profile_column(
    dataframe: pd.DataFrame, column_name: str, ambiguous_columns: list[str] | None = None
) -> ColumnProfile:
    """Build a :class:`ColumnProfile` for ``column_name`` in ``dataframe``.

    Args:
        dataframe: The dataframe containing the column.
        column_name: Which column to profile.
        ambiguous_columns: Pre-computed result of
            :func:`~src.readers.type_inference.
            find_ambiguous_type_columns` for the whole dataframe, if
            already available. Accepted as a parameter (rather than
            this function always recomputing it) because
            :func:`~src.analysis.dataset_profile.profile_dataset`
            profiles every column in a loop and would otherwise
            recompute this dataframe-wide check once per column —
            wasteful for a wide dataframe. If omitted, this function
            computes it itself, so :func:`profile_column` remains
            correct and usable on its own.
    """
    series = dataframe[column_name]
    total_rows = len(series)

    if ambiguous_columns is None:
        ambiguous_columns = find_ambiguous_type_columns(dataframe)

    missing_count = int(series.isna().sum())
    missing_percentage = round((missing_count / total_rows * 100), 1) if total_rows > 0 else 0.0
    unique_count = int(series.nunique(dropna=True))

    profile = ColumnProfile(
        name=column_name,
        dtype=str(series.dtype),
        missing_count=missing_count,
        missing_percentage=missing_percentage,
        unique_count=unique_count,
        is_ambiguous_type=column_name in ambiguous_columns,
    )

    if pd.api.types.is_datetime64_any_dtype(series):
        non_null = series.dropna()
        if len(non_null) > 0:
            profile.datetime_range = (non_null.min(), non_null.max())
    elif pd.api.types.is_numeric_dtype(series) and not profile.is_ambiguous_type:
        non_null = series.dropna()
        if len(non_null) > 0:
            profile.numeric_stats = {
                "min": float(non_null.min()),
                "max": float(non_null.max()),
                "mean": float(non_null.mean()),
                "median": float(non_null.median()),
                "std": float(non_null.std()) if len(non_null) > 1 else 0.0,
            }
    else:
        value_counts = series.value_counts(dropna=True).head(_TOP_VALUES_COUNT)
        profile.top_values = list(value_counts.items())

    return profile
