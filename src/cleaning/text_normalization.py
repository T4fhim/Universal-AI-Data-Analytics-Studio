# File: src/cleaning/text_normalization.py
"""Trim whitespace and normalize casing on text columns.

Unlike :mod:`~src.cleaning.missing_values` and
:mod:`~src.cleaning.duplicates`, :class:`NormalizeText` requires an
explicit ``columns`` list rather than defaulting to "all columns" or
attempting to auto-detect which columns are text. Auto-detection was
considered and rejected: a column with ``object`` or ``StringDtype``
dtype is not reliably "meant to be text" — milestone 2a's own testing
found that pandas can assign these dtypes to columns that are actually
ambiguous numeric data (see
:func:`~src.readers.type_inference.find_ambiguous_type_columns`'s
documented history). Silently applying case normalization to a column
the user did not intend to treat as text is a real risk of corrupting
data in a way that would not be immediately obvious; requiring
explicit column names makes the operation's scope an explicit user
choice rather than a heuristic guess.
"""

from __future__ import annotations

import pandas as pd

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.cleaning.base_operation import BaseOperation
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_VALID_CASE_MODES = {"lower", "upper", "title", None}


class NormalizeText(BaseOperation):
    """Trims leading/trailing whitespace and optionally normalizes casing."""

    @classmethod
    def apply(
        cls,
        dataset: Dataset,
        columns: list[str],
        trim_whitespace: bool = True,
        case: str | None = None,
    ) -> Dataset:
        """Normalize text in ``columns``.

        Args:
            dataset: The source dataset.
            columns: Columns to normalize. Required (not optional) —
                see the module docstring for why this operation does
                not default to "all columns" or auto-detect text
                columns.
            trim_whitespace: If ``True`` (the default), strips leading
                and trailing whitespace from every value in
                ``columns``.
            case: If set, normalizes casing: ``"lower"``, ``"upper"``,
                or ``"title"`` (each word capitalized). ``None`` (the
                default) leaves casing unchanged.

        Raises:
            ServiceError: If ``columns`` is empty, any name in it does
                not exist in ``dataset``, or ``case`` is not one of
                the recognized values.
        """
        if not columns:
            raise ServiceError(
                "NormalizeText requires at least one column to be "
                "specified; it does not operate on all columns by "
                "default (see this operation's module docstring for "
                "why)."
            )

        missing = [c for c in columns if c not in dataset.dataframe.columns]
        if missing:
            raise ServiceError(
                f"Column(s) not found in dataset '{dataset.name}': "
                f"{', '.join(missing)}. Available columns: "
                f"{', '.join(str(c) for c in dataset.dataframe.columns)}."
            )

        if case not in _VALID_CASE_MODES:
            raise ServiceError(
                f"Invalid case mode: {case!r}. Must be one of "
                f"'lower', 'upper', 'title', or None."
            )

        normalized_dataframe = dataset.dataframe.copy()
        applied_operations = []

        for column in columns:
            series = normalized_dataframe[column]
            original_na_mask = series.isna()

            # .astype(str) before .str accessor use is deliberate: a
            # column that is nominally text-dtype can still contain
            # non-string values (NaN, or a stray numeric value in an
            # otherwise-text column) that .str methods would either
            # skip silently or raise on depending on pandas version.
            # Converting to str first makes the operation's behavior
            # on such values explicit and consistent rather than
            # dependent on pandas internals this project does not
            # want to be coupled to.
            #
            # BUG FOUND BY TESTING, FIXED HERE: astype(str) converts a
            # genuinely missing (NaN) value into the literal 3-character
            # string "nan" — it does not preserve missingness. Left
            # unfixed, a column's missing values would silently become
            # real (wrong) text data that any later isna() check would
            # miss. original_na_mask is captured above, before the string
            # conversion, and used below to restore actual NaN at those
            # positions after the string operations run.
            string_series = series.astype(str)

            if trim_whitespace:
                string_series = string_series.str.strip()

            if case == "lower":
                string_series = string_series.str.lower()
            elif case == "upper":
                string_series = string_series.str.upper()
            elif case == "title":
                string_series = string_series.str.title()

            string_series[original_na_mask] = pd.NA
            normalized_dataframe[column] = string_series

        if trim_whitespace:
            applied_operations.append("trimmed whitespace")
        if case:
            applied_operations.append(f"normalized to {case} case")

        description = (
            f"Text normalization ({', '.join(applied_operations)}) "
            f"on column(s): {', '.join(columns)}."
        )

        _logger.info("NormalizeText on '%s': %s", dataset.name, description)

        return Dataset(
            name=dataset.name,
            dataframe=normalized_dataframe,
            source_format=dataset.source_format,
            source_path=dataset.source_path,
            parent_dataset_id=dataset.dataset_id,
            derivation_description=description,
        )
