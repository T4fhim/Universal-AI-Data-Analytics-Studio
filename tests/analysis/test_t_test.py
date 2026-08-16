# File: tests/analysis/test_t_test.py
"""Tests for src.analysis.t_test."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.t_test import independent_t_test, paired_t_test
from src.core.exceptions import ServiceError


def _grouped_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "score": np.concatenate([rng.normal(50, 5, 30), rng.normal(60, 5, 30)]),
            "group": ["a"] * 30 + ["b"] * 30,
        }
    )


def test_independent_t_test_detects_real_difference() -> None:
    result = independent_t_test(_grouped_dataframe(), "score", "group", "a", "b")
    assert result.test_type == "independent"
    assert result.significant_at_0_05 is True
    assert result.group_a_mean < result.group_b_mean


def test_independent_t_test_missing_column_raises() -> None:
    with pytest.raises(ServiceError, match="not found"):
        independent_t_test(_grouped_dataframe(), "nope", "group", "a", "b")


def test_independent_t_test_too_few_observations_raises() -> None:
    df = pd.DataFrame({"score": [1.0], "group": ["a"]})
    with pytest.raises(ServiceError, match="at least 2"):
        independent_t_test(df, "score", "group", "a", "b")


def test_paired_t_test_identical_columns_not_significant() -> None:
    df = pd.DataFrame({"before": [1.0, 2.0, 3.0, 4.0], "after": [1.0, 2.0, 3.0, 4.0]})
    result = paired_t_test(df, "before", "after")
    assert result.test_type == "paired"
    assert result.significant_at_0_05 is False


def test_paired_t_test_too_few_rows_raises() -> None:
    df = pd.DataFrame({"before": [1.0], "after": [1.0]})
    with pytest.raises(ServiceError, match="At least 2"):
        paired_t_test(df, "before", "after")
