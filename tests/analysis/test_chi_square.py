# File: tests/analysis/test_chi_square.py
"""Tests for src.analysis.chi_square."""

from __future__ import annotations

import pandas as pd
import pytest

from src.analysis.chi_square import chi_square_test
from src.core.exceptions import ServiceError


def _dependent_dataframe() -> pd.DataFrame:
    # Constructed so 'category' strongly predicts 'outcome' — chi2 test
    # should find them dependent (reject independence).
    return pd.DataFrame(
        {
            "category": ["x"] * 40 + ["y"] * 40,
            "outcome": ["pass"] * 35 + ["fail"] * 5 + ["fail"] * 35 + ["pass"] * 5,
        }
    )


def test_chi_square_test_detects_dependence() -> None:
    result = chi_square_test(_dependent_dataframe(), "category", "outcome")
    assert result.significant_at_0_05 is True
    assert result.degrees_of_freedom == 1


def test_chi_square_test_too_few_categories_raises() -> None:
    df = pd.DataFrame({"a": ["x"] * 5, "b": ["y"] * 5})
    with pytest.raises(ServiceError, match="at least 2 categories"):
        chi_square_test(df, "a", "b")


def test_chi_square_test_missing_column_raises() -> None:
    with pytest.raises(ServiceError):
        chi_square_test(_dependent_dataframe(), "nope", "outcome")
