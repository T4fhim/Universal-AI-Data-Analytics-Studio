# File: src/cleaning/duplicates.py
"""Remove duplicate rows from a dataset."""

from __future__ import annotations

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.cleaning.base_operation import BaseOperation
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)


class DropDuplicates(BaseOperation):
    """Removes duplicate rows, keeping the first occurrence of each."""

    @classmethod
    def apply(cls, dataset: Dataset, columns: list[str] | None = None) -> Dataset:
        """Drop duplicate rows, considering ``columns`` (or all columns, if omitted).

        Args:
            dataset: The source dataset.
            columns: Columns to consider when identifying duplicates.
                If omitted, two rows are duplicates only if every
                column matches, matching
                ``pandas.DataFrame.drop_duplicates()``'s default.
            Always keeps the first occurrence of each duplicate group
            and drops the rest — this is not currently configurable,
            since "keep first" is the overwhelmingly common case and
            "keep last" can be achieved by reversing the dataframe
            first if a future need for it arises.

        Raises:
            ServiceError: If any name in ``columns`` does not exist in
                ``dataset``.
        """
        if columns:
            missing = [c for c in columns if c not in dataset.dataframe.columns]
            if missing:
                raise ServiceError(
                    f"Column(s) not found in dataset '{dataset.name}': "
                    f"{', '.join(missing)}. Available columns: "
                    f"{', '.join(str(c) for c in dataset.dataframe.columns)}."
                )

        subset_arg = columns if columns else None
        deduplicated = dataset.dataframe.drop_duplicates(subset=subset_arg, keep="first")

        rows_dropped = len(dataset.dataframe) - len(deduplicated)
        column_description = (
            f"considering {', '.join(columns)}" if columns else "considering all columns"
        )

        _logger.info(
            "DropDuplicates on '%s': dropped %d duplicate row(s), %s.",
            dataset.name,
            rows_dropped,
            column_description,
        )

        return Dataset(
            name=dataset.name,
            dataframe=deduplicated.reset_index(drop=True),
            source_format=dataset.source_format,
            source_path=dataset.source_path,
            parent_dataset_id=dataset.dataset_id,
            derivation_description=(
                f"Dropped {rows_dropped} duplicate row(s), {column_description}."
            ),
        )
