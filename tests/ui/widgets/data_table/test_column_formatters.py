# File: tests/ui/widgets/data_table/test_column_formatters.py
"""Tests for column_formatters.py -- pure functions, zero Qt."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.ui.widgets.data_table.column_formatters import (
    MISSING_DISPLAY,
    format_value,
    is_missing,
)


def test_is_missing_none() -> None:
    assert is_missing(None) is True


def test_is_missing_nan() -> None:
    assert is_missing(float("nan")) is True
    assert is_missing(np.nan) is True


def test_is_missing_nat() -> None:
    assert is_missing(pd.NaT) is True


def test_is_missing_real_values() -> None:
    assert is_missing(0) is False
    assert (
        is_missing("") is False
    )  # an empty string is a real value, not absence of one
    assert is_missing(False) is False
    assert is_missing("text") is False


def test_format_value_missing_renders_em_dash() -> None:
    assert format_value(None) == MISSING_DISPLAY
    assert format_value(float("nan")) == MISSING_DISPLAY


def test_format_value_integer_valued_float_has_no_trailing_zero() -> None:
    assert format_value(3.0) == "3"


def test_format_value_non_integer_float_keeps_precision() -> None:
    assert format_value(3.14159265) == "3.14159"


def test_format_value_bool() -> None:
    assert format_value(True) == "True"
    assert format_value(False) == "False"


def test_format_value_string_passthrough() -> None:
    assert format_value("hello") == "hello"


def test_format_value_timestamp() -> None:
    ts = pd.Timestamp("2024-01-01 12:30:00")
    assert "2024-01-01" in format_value(ts)


def test_is_missing_does_not_raise_on_list_valued_cell() -> None:
    """pd.isna() raises ValueError for array-like values -- a cell that
    happens to hold a list is a real, if unusual, value, not an absence
    of one, and must not crash the model's data() call.
    """
    assert is_missing([1, 2, 3]) is False
