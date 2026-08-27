# File: tests/analysis/test_regression.py
"""Tests for src.analysis.regression."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.regression import linear_regression
from src.core.exceptions import ServiceError


def _linear_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(3)
    x = np.arange(50, dtype=float)
    noise = rng.normal(0, 0.5, 50)
    return pd.DataFrame({"x": x, "y": 2 * x + 5 + noise})


def test_linear_regression_recovers_known_relationship() -> None:
    result = linear_regression(_linear_dataframe(), "y", ["x"])
    assert result.coefficients["x"] == pytest.approx(2.0, abs=0.1)
    assert result.intercept == pytest.approx(5.0, abs=0.5)
    assert result.r_squared > 0.99


def test_linear_regression_multiple_features() -> None:
    rng = np.random.default_rng(9)
    df = pd.DataFrame(
        {
            "x1": rng.normal(0, 1, 60),
            "x2": rng.normal(0, 1, 60),
        }
    )
    df["y"] = 3 * df["x1"] - 2 * df["x2"] + 1
    result = linear_regression(df, "y", ["x1", "x2"])
    assert result.coefficients["x1"] == pytest.approx(3.0, abs=0.1)
    assert result.coefficients["x2"] == pytest.approx(-2.0, abs=0.1)


def test_linear_regression_empty_features_raises() -> None:
    with pytest.raises(ServiceError, match="at least one"):
        linear_regression(_linear_dataframe(), "y", [])


def test_linear_regression_non_numeric_raises() -> None:
    df = pd.DataFrame({"x": ["a", "b", "c"], "y": [1.0, 2.0, 3.0]})
    with pytest.raises(ServiceError, match="must be numeric"):
        linear_regression(df, "y", ["x"])
