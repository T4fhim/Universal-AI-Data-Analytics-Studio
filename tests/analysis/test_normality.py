# File: tests/analysis/test_normality.py
"""Tests for src.analysis.normality."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.normality import check_normality
from src.core.exceptions import ServiceError


def test_normality_shapiro_on_normal_data_appears_normal() -> None:
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"x": rng.normal(0, 1, 100)})
    result = check_normality(df, "x", method="shapiro_wilk")
    assert result.method == "shapiro_wilk"
    assert result.appears_normal_at_0_05 is True


def test_normality_shapiro_on_skewed_data_rejects_normal() -> None:
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"x": rng.exponential(1.0, 200)})
    result = check_normality(df, "x", method="shapiro_wilk")
    assert result.appears_normal_at_0_05 is False


def test_normality_dagostino_method() -> None:
    rng = np.random.default_rng(4)
    df = pd.DataFrame({"x": rng.normal(0, 1, 100)})
    result = check_normality(df, "x", method="dagostino_pearson")
    assert result.method == "dagostino_pearson"


def test_normality_invalid_method_raises() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    with pytest.raises(ServiceError, match="Invalid method"):
        check_normality(df, "x", method="nope")


def test_normality_too_few_values_raises() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0]})
    with pytest.raises(ServiceError, match="At least 3"):
        check_normality(df, "x")
