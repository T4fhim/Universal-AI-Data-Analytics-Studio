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
    unregister_operation,
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
    # _REGISTRY is process-global module state (see operation_registry.py's own
    # "populate at import time" design, mirroring chart_registry/reader_registry) --
    # unregistered here so this test does not leak "_test_only_operation" into every other
    # test in the suite that calls list_operations()/get_operation() afterward (notably
    # tests/ui/workbench/test_clean_page.py's exact-count assertions).
    register_operation("_test_only_operation", DropMissingValues)
    try:
        assert get_operation("_test_only_operation") is DropMissingValues
    finally:
        unregister_operation("_test_only_operation")
