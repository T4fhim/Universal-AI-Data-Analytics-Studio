# File: tests/analysis/test_clustering.py
"""Tests for src.analysis.clustering."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.clustering import k_means_clustering
from src.core.exceptions import ServiceError


def _well_separated_clusters() -> pd.DataFrame:
    rng = np.random.default_rng(21)
    cluster_a = rng.normal(0, 0.5, (30, 2))
    cluster_b = rng.normal(20, 0.5, (30, 2))
    points = np.vstack([cluster_a, cluster_b])
    return pd.DataFrame(points, columns=["x", "y"])


def test_k_means_clustering_recovers_two_well_separated_clusters() -> None:
    result = k_means_clustering(_well_separated_clusters(), k=2)
    assert result.k == 2
    assert sum(result.cluster_sizes.values()) == 60
    # Each true cluster should map cleanly to one label (allow either
    # 30/30 split ordering since k-means label numbering is arbitrary).
    assert sorted(result.cluster_sizes.values()) == [30, 30]


def test_k_means_clustering_k_below_minimum_raises() -> None:
    with pytest.raises(ServiceError, match="at least 2"):
        k_means_clustering(_well_separated_clusters(), k=1)


def test_k_means_clustering_k_exceeds_rows_raises() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0], "y": [1.0, 2.0]})
    with pytest.raises(ServiceError, match="cannot exceed"):
        k_means_clustering(df, k=5)


def test_k_means_clustering_too_few_columns_raises() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    with pytest.raises(ServiceError, match="at least 2 numeric"):
        k_means_clustering(df, k=2)
