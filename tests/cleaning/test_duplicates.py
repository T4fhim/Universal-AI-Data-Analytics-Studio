# File: tests/cleaning/test_duplicates.py
"""Tests for src.cleaning.duplicates.DropDuplicates.

Covers the standard, zero-duplicate, and all-duplicate boundary cases,
the ServiceError for an unknown column, and the never-mutate-in-place
contract every BaseOperation must uphold (CLAUDE.md: "Cleaning
operations never mutate a Dataset in place").
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.cleaning.duplicates import DropDuplicates
from src.core.exceptions import ServiceError
from src.services.workspace_service import Dataset


def _make_dataset(data: dict[str, list]) -> Dataset:
    return Dataset(
        name="test-dataset",
        dataframe=pd.DataFrame(data),
        source_format="csv",
    )


def test_drop_duplicates_standard_case_drops_only_duplicate_rows() -> None:
    dataset = _make_dataset({"a": [1, 1, 2], "b": ["x", "x", "y"]})

    result = DropDuplicates.apply(dataset)

    assert len(result.dataframe) == 2
    assert list(result.dataframe["a"]) == [1, 2]


def test_drop_duplicates_zero_duplicates_case_drops_nothing() -> None:
    dataset = _make_dataset({"a": [1, 2, 3]})

    result = DropDuplicates.apply(dataset)

    assert len(result.dataframe) == len(dataset.dataframe)
    assert list(result.dataframe["a"]) == [1, 2, 3]


def test_drop_duplicates_all_duplicate_case_keeps_only_first_row() -> None:
    dataset = _make_dataset({"a": [7, 7, 7, 7]})

    result = DropDuplicates.apply(dataset)

    assert len(result.dataframe) == 1
    assert list(result.dataframe["a"]) == [7]


def test_drop_duplicates_raises_service_error_for_unknown_column() -> None:
    dataset = _make_dataset({"a": [1, 2]})

    with pytest.raises(ServiceError):
        DropDuplicates.apply(dataset, columns=["not_a_real_column"])


def test_drop_duplicates_returns_new_dataset_with_lineage_and_leaves_source_untouched() -> (
    None
):
    dataset = _make_dataset({"a": [1, 1, 2]})
    original_row_count = len(dataset.dataframe)

    result = DropDuplicates.apply(dataset)

    # Never-mutate-in-place: a distinct Dataset object, source
    # untouched, lineage fields set to trace back to the parent.
    assert result is not dataset
    assert result.dataset_id != dataset.dataset_id
    assert len(dataset.dataframe) == original_row_count
    assert result.parent_dataset_id == dataset.dataset_id
    assert result.derivation_description is not None
