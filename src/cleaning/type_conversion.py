# File: src/cleaning/type_conversion.py
"""Convert a column's data type — the direct follow-up to milestone 2a's ambiguous-type warnings.

Every reader in this project can report that a column has an
ambiguous type (see
:func:`~src.readers.type_inference.find_ambiguous_type_columns`) but
none of them attempt to fix it — that was an explicit, documented
scope boundary in every reader that surfaces the warning. This module
is where that boundary's other side lives: :class:`ConvertType` is the
operation a user reaches for once a reader has told them a column
needs attention.

The one thing this operation refuses to do silently: pandas'
``pd.to_numeric(..., errors="coerce")`` converts unparseable values to
``NaN`` without reporting which values those were. This operation
does the coercion but reports exactly how many values failed and
(when there are few enough to be genuinely useful in a message, not
so many that it turns the warning into a wall of text) samples what
they actually were — a caller cannot see "12 values failed to convert"
and mistake that for "the operation worked flawlessly."
"""

from __future__ import annotations

import pandas as pd

from src.cleaning.base_operation import BaseOperation
from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.services.workspace_service import Dataset

_logger = get_logger(__name__)

_VALID_TARGET_TYPES = {"numeric", "integer", "string", "boolean", "datetime"}

# When reporting values that failed conversion, show at most this many
# examples in the description — enough to be genuinely useful for
# spotting a pattern (a consistent placeholder like "N/A" or "unknown"
# rather than truly random garbage), not so many that the message
# becomes unreadable for a column with hundreds of failures.
_MAX_FAILURE_EXAMPLES = 5


class ConvertType(BaseOperation):
    """Converts a column to a target type, reporting values that failed to convert."""

    @classmethod
    def apply(cls, dataset: Dataset, column: str, target_type: str) -> Dataset:
        """Convert ``column`` in ``dataset`` to ``target_type``.

        Args:
            dataset: The source dataset.
            column: The column to convert. A single column, not a
                list — unlike the other operations in this package,
                type conversion is a per-column decision that rarely
                makes sense to batch (different columns usually need
                different target types), so batching was not built in
                to avoid a signature that implies "convert several
                columns to the same type" is the common case when it
                is not.
            target_type: One of ``"numeric"``, ``"integer"``,
                ``"string"``, ``"boolean"``, or ``"datetime"``.

        Raises:
            ServiceError: If ``column`` does not exist in ``dataset``,
                or ``target_type`` is not one of the recognized
                values.
        """
        if column not in dataset.dataframe.columns:
            raise ServiceError(
                f"Column '{column}' not found in dataset '{dataset.name}'. "
                f"Available columns: "
                f"{', '.join(str(c) for c in dataset.dataframe.columns)}."
            )

        if target_type not in _VALID_TARGET_TYPES:
            raise ServiceError(
                f"Invalid target_type: {target_type!r}. Must be one "
                f"of: {', '.join(sorted(_VALID_TARGET_TYPES))}."
            )

        converted_dataframe = dataset.dataframe.copy()
        original_series = converted_dataframe[column]

        converted_series, failed_values = cls._convert_series(original_series, target_type)
        converted_dataframe[column] = converted_series

        description = cls._build_description(column, target_type, failed_values)
        _logger.info("ConvertType on '%s': %s", dataset.name, description)

        return Dataset(
            name=dataset.name,
            dataframe=converted_dataframe,
            source_format=dataset.source_format,
            source_path=dataset.source_path,
            parent_dataset_id=dataset.dataset_id,
            derivation_description=description,
        )

    @classmethod
    def _convert_series(
        cls, series: pd.Series, target_type: str
    ) -> tuple[pd.Series, list]:
        """Convert ``series`` to ``target_type``, returning (converted, failed_original_values).

        ``failed_original_values`` holds the *original* values that
        could not convert — not their post-conversion ``NaN``
        placeholder — since reporting "these specific inputs failed"
        is only useful if it names what the input actually was.
        """
        if target_type == "numeric":
            converted = pd.to_numeric(series, errors="coerce")
        elif target_type == "integer":
            # Two-step: to_numeric first (to genuinely coerce
            # unparseable values to NaN, same as the "numeric" case),
            # then a nullable integer dtype capable of holding both
            # integers and NaN — plain int64 cannot represent NaN at
            # all, which would make failed conversions impossible to
            # represent rather than merely absent.
            numeric = pd.to_numeric(series, errors="coerce")
            converted = numeric.astype("Int64")
        elif target_type == "string":
            # Every value can be stringified; there is no failure
            # case for this direction.
            converted = series.astype(str)
        elif target_type == "boolean":
            converted = cls._convert_to_boolean(series)
        elif target_type == "datetime":
            converted = pd.to_datetime(series, errors="coerce")
        else:
            # Unreachable given apply()'s validation above; present
            # only so this method fails loudly rather than silently
            # returning an unconverted series if a target type is
            # ever added to _VALID_TARGET_TYPES without a
            # corresponding branch here being added too.
            raise ServiceError(f"No conversion implemented for target_type: {target_type!r}")

        failed_mask = converted.isna() & series.notna()
        failed_values = series[failed_mask].tolist()

        return converted, failed_values

    @classmethod
    def _convert_to_boolean(cls, series: pd.Series) -> pd.Series:
        """Convert common boolean-like text representations to actual booleans.

        Recognizes, case-insensitively: true/false, yes/no, y/n, 1/0
        (as strings — a genuinely numeric 1/0 column converts via
        pandas' own bool casting without needing this mapping at all,
        since ``bool(1) == True`` already). Anything else fails to
        convert (becomes ``NaN`` via the same failed-value reporting
        every other target type uses), rather than this method
        guessing at values it does not recognize with confidence.
        """
        true_values = {"true", "yes", "y", "1"}
        false_values = {"false", "no", "n", "0"}

        def _map_value(value):
            if pd.isna(value):
                return pd.NA
            text = str(value).strip().lower()
            if text in true_values:
                return True
            if text in false_values:
                return False
            return pd.NA

        return series.apply(_map_value).astype("boolean")

    @classmethod
    def _build_description(
        cls, column: str, target_type: str, failed_values: list
    ) -> str:
        """Build a human-readable summary, including a sample of failed values if any."""
        if not failed_values:
            return f"Converted column '{column}' to {target_type} (no failures)."

        sample = failed_values[:_MAX_FAILURE_EXAMPLES]
        sample_text = ", ".join(repr(v) for v in sample)
        if len(failed_values) > _MAX_FAILURE_EXAMPLES:
            sample_text += f", and {len(failed_values) - _MAX_FAILURE_EXAMPLES} more"

        return (
            f"Converted column '{column}' to {target_type}. "
            f"{len(failed_values)} value(s) could not be converted and "
            f"became missing: {sample_text}."
        )
