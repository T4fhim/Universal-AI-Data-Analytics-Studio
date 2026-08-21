# File: src/cleaning/missing_values.py
"""Drop or fill missing values in a dataset.

Two operations: :class:`DropMissingValues` removes rows with missing
values in specified (or all) columns; :class:`FillMissingValues`
replaces missing values with a supplied fill value. Both accept an
optional ``columns`` parameter restricting the operation to specific
columns — omitting it applies the operation across every column, which
matches pandas' own ``dropna()``/``fillna()`` defaults and avoids
requiring the common "just clean up everything" case to enumerate
every column name explicitly.
"""

from __future__ import annotations

from typing import Any

from src.cleaning.base_operation import BaseOperation
from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)


def _validate_columns(dataset: Dataset, columns: list[str] | None) -> None:
    """Raise ServiceError if any requested column does not exist in the dataset.

    Shared by both operations in this module rather than duplicated,
    since both need the identical check before proceeding.
    """
    if columns is None:
        return
    missing = [c for c in columns if c not in dataset.dataframe.columns]
    if missing:
        raise ServiceError(
            f"Column(s) not found in dataset '{dataset.name}': "
            f"{', '.join(missing)}. Available columns: "
            f"{', '.join(str(c) for c in dataset.dataframe.columns)}."
        )


class DropMissingValues(BaseOperation):
    """Removes rows containing missing values."""

    @classmethod
    def apply(cls, dataset: Dataset, columns: list[str] | None = None) -> Dataset:
        """Drop rows with a missing value in ``columns`` (or any column, if omitted).

        Args:
            dataset: The source dataset.
            columns: Columns to check for missing values. If omitted,
                a row is dropped if it has a missing value in *any*
                column, matching ``pandas.DataFrame.dropna()``'s
                default behavior.

        Raises:
            ServiceError: If any name in ``columns`` does not exist in
                ``dataset``.
        """
        _validate_columns(dataset, columns)

        subset_arg = columns if columns else None
        cleaned_dataframe = dataset.dataframe.dropna(subset=subset_arg)

        rows_dropped = len(dataset.dataframe) - len(cleaned_dataframe)
        column_description = f"in {', '.join(columns)}" if columns else "in any column"

        _logger.info(
            "DropMissingValues on '%s': dropped %d row(s) %s.",
            dataset.name,
            rows_dropped,
            column_description,
        )

        return Dataset(
            name=dataset.name,
            dataframe=cleaned_dataframe.reset_index(drop=True),
            source_format=dataset.source_format,
            source_path=dataset.source_path,
            parent_dataset_id=dataset.dataset_id,
            derivation_description=(
                f"Dropped {rows_dropped} row(s) with missing values "
                f"{column_description}."
            ),
        )


class FillMissingValues(BaseOperation):
    """Replaces missing values with a supplied fill value."""

    @classmethod
    def apply(
        cls,
        dataset: Dataset,
        fill_value: Any,
        columns: list[str] | None = None,
    ) -> Dataset:
        """Fill missing values in ``columns`` (or all columns) with ``fill_value``.

        Args:
            dataset: The source dataset.
            fill_value: The value to substitute for missing entries.
                Applied as-is via ``pandas.DataFrame.fillna()`` — no
                type coercion is attempted (filling a numeric column
                with a string value, for example, is permitted here
                and will produce a mixed-type column; that is the
                caller's responsibility to avoid, not this operation's
                to prevent, matching how
                :func:`~src.readers.type_inference.
                find_ambiguous_type_columns` already treats mixed
                types as something to report, not something a reader
                or operation silently corrects).
            columns: Columns to fill. If omitted, applies to every
                column.

        Raises:
            ServiceError: If any name in ``columns`` does not exist in
                ``dataset``.
        """
        _validate_columns(dataset, columns)

        missing_before = int(dataset.dataframe.isna().sum().sum())

        if columns:
            filled_dataframe = dataset.dataframe.copy()
            for column in columns:
                filled_dataframe[column] = filled_dataframe[column].fillna(fill_value)
        else:
            filled_dataframe = dataset.dataframe.fillna(fill_value)

        missing_after = int(filled_dataframe.isna().sum().sum())
        values_filled = missing_before - missing_after
        column_description = f"in {', '.join(columns)}" if columns else "in all columns"

        _logger.info(
            "FillMissingValues on '%s': filled %d value(s) %s with %r.",
            dataset.name,
            values_filled,
            column_description,
            fill_value,
        )

        return Dataset(
            name=dataset.name,
            dataframe=filled_dataframe,
            source_format=dataset.source_format,
            source_path=dataset.source_path,
            parent_dataset_id=dataset.dataset_id,
            derivation_description=(
                f"Filled {values_filled} missing value(s) {column_description} "
                f"with {fill_value!r}."
            ),
        )
