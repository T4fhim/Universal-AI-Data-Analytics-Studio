# File: tests/analysis/test_anova.py
"""Tests for src.analysis.anova."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.anova import one_way_anova
from src.core.exceptions import ServiceError


def _three_group_dataframe() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    return pd.DataFrame(
        {
            "value": np.concatenate(
                [rng.normal(10, 2, 20), rng.normal(20, 2, 20), rng.normal(30, 2, 20)]
            ),
            "group": ["a"] * 20 + ["b"] * 20 + ["c"] * 20,
        }
    )


def test_one_way_anova_detects_real_difference() -> None:
    result = one_way_anova(_three_group_dataframe(), "value", "group")
    assert result.significant_at_0_05 is True
    assert set(result.group_means) == {"a", "b", "c"}


def test_one_way_anova_too_few_groups_raises() -> None:
    df = pd.DataFrame({"value": [1.0, 2.0, 3.0, 4.0], "group": ["a", "a", "b", "b"]})
    with pytest.raises(ServiceError, match="at least 3"):
        one_way_anova(df, "value", "group")


def test_one_way_anova_missing_column_raises() -> None:
    with pytest.raises(ServiceError, match="not found"):
        one_way_anova(_three_group_dataframe(), "nope", "group")
