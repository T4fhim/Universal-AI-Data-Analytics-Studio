# File: src/analysis/dataset_profile.py
"""Dataset-level profiling: aggregates column profiles plus dataset-wide stats."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.core.logger import get_logger
from src.analysis.column_profile import ColumnProfile, profile_column
from src.readers.type_inference import find_ambiguous_type_columns
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)


@dataclass
class DatasetProfile:
    """Aggregate profile of an entire dataset.

    Attributes:
        dataset_name: Name of the profiled dataset, at profiling time
            — not a live reference to the ``Dataset`` object, since a
            profile is a snapshot, not a view that should change if
            the dataset is later renamed or re-derived.
        row_count: Total rows.
        column_count: Total columns.
        duplicate_row_count: Rows that are exact duplicates of an
            earlier row (see :class:`~src.cleaning.duplicates.
            DropDuplicates`, which this number is meant to inform
            the decision to run).
        memory_usage_bytes: Approximate in-memory size of the
            dataframe, via ``pandas.DataFrame.memory_usage(deep=True)``
            — ``deep=True`` is used deliberately despite being slower,
            since without it, object-dtype columns (most text columns)
            report only the size of their pointers, not their actual
            string content, which would make this number misleading
            for exactly the columns most likely to be large.
        column_profiles: One :class:`~src.analysis.column_profile.
            ColumnProfile` per column, in the dataframe's original
            column order.
        ambiguous_type_columns: Column names flagged by
            :func:`~src.readers.type_inference.
            find_ambiguous_type_columns` — duplicated here at the
            dataset level (each affected column's own profile also
            has ``is_ambiguous_type=True``) purely for convenience, so
            a caller wanting "which columns need attention" does not
            need to filter ``column_profiles`` itself.
    """

    dataset_name: str
    row_count: int
    column_count: int
    duplicate_row_count: int
    memory_usage_bytes: int
    column_profiles: list[ColumnProfile] = field(default_factory=list)
    ambiguous_type_columns: list[str] = field(default_factory=list)


def profile_dataset(dataset: Dataset) -> DatasetProfile:
    """Build a :class:`DatasetProfile` for ``dataset``."""
    dataframe = dataset.dataframe

    ambiguous_columns = find_ambiguous_type_columns(dataframe)

    column_profiles = [
        profile_column(dataframe, column_name, ambiguous_columns=ambiguous_columns)
        for column_name in dataframe.columns
    ]

    duplicate_row_count = int(dataframe.duplicated(keep="first").sum())
    memory_usage_bytes = int(dataframe.memory_usage(deep=True).sum())

    _logger.info(
        "Profiled dataset '%s': %d rows, %d columns, %d duplicate row(s), "
        "%d ambiguous-type column(s).",
        dataset.name,
        len(dataframe),
        len(dataframe.columns),
        duplicate_row_count,
        len(ambiguous_columns),
    )

    return DatasetProfile(
        dataset_name=dataset.name,
        row_count=len(dataframe),
        column_count=len(dataframe.columns),
        duplicate_row_count=duplicate_row_count,
        memory_usage_bytes=memory_usage_bytes,
        column_profiles=column_profiles,
        ambiguous_type_columns=ambiguous_columns,
    )
