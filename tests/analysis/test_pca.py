# File: tests/analysis/test_pca.py
"""Tests for src.analysis.pca."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.pca import compute_pca
from src.core.exceptions import ServiceError


def _correlated_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    x = rng.normal(0, 1, 100)
    # y is almost perfectly correlated with x -> first component should
    # explain nearly all the variance.
    y = x * 2 + rng.normal(0, 0.01, 100)
    z = rng.normal(0, 1, 100)
    return pd.DataFrame({"x": x, "y": y, "z": z})


def test_compute_pca_first_component_dominates_when_columns_correlated() -> None:
    result = compute_pca(_correlated_dataframe())
    assert len(result.explained_variance_ratio) == 3
    assert result.explained_variance_ratio[0] > 0.6
    assert result.cumulative_variance_ratio[-1] == pytest.approx(1.0, abs=1e-6)


def test_compute_pca_respects_explicit_columns_and_n_components() -> None:
    result = compute_pca(
        _correlated_dataframe(), columns=["x", "y", "z"], n_components=2
    )
    assert result.included_columns == ["x", "y", "z"]
    assert len(result.explained_variance_ratio) == 2
    assert result.transformed.shape == (100, 2)


def test_compute_pca_too_few_columns_raises() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    with pytest.raises(ServiceError, match="at least 2"):
        compute_pca(df)


def test_compute_pca_n_components_too_large_raises() -> None:
    with pytest.raises(ServiceError, match="cannot exceed"):
        compute_pca(_correlated_dataframe(), n_components=5)
