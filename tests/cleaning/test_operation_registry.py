# File: tests/cleaning/test_operation_registry.py
"""Tests for src.cleaning.operation_registry."""

from __future__ import annotations

import pytest

from src.cleaning.duplicates import DropDuplicates
from src.cleaning.missing_values import DropMissingValues
from src.cleaning.operation_registry import (
    get_operation,
    list_operations,
    register_operation,
)
from src.core.exceptions import ServiceError


def test_builtin_operations_are_registered() -> None:
    operations = list_operations()
    assert operations["drop_missing_values"] is DropMissingValues
    assert operations["drop_duplicates"] is DropDuplicates
    assert len(operations) == 5


def test_get_operation_unknown_name_raises() -> None:
    with pytest.raises(ServiceError, match="Unknown cleaning operation"):
        get_operation("not_a_real_operation")


def test_register_operation_duplicate_name_raises() -> None:
    with pytest.raises(ServiceError, match="already registered"):
        register_operation("drop_duplicates", DropMissingValues)


def test_register_operation_new_name_succeeds() -> None:
    register_operation("_test_only_operation", DropMissingValues)
    assert get_operation("_test_only_operation") is DropMissingValues
