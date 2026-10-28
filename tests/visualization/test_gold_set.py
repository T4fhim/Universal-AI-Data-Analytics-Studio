# File: tests/visualization/test_gold_set.py
"""Invariants of the chart-intelligence gold set (``tests/visualization/gold_set.py``).

These test the *measuring instrument*, not the recommender: if a generator drifted, a case named a chart the
registry does not have, or ``evaluate`` swallowed a crash, every later quality number (CI.3's bar, CI.7's AI
comparison) would be measured against a moving or wrong target. The recommender's own quality is deliberately not
asserted here; the baseline is recorded in ``plans/phase-4-ci0-findings.md`` and CI.3 owns the bar.
"""

from __future__ import annotations

import pandas as pd
import pytest

from tests.visualization.gold_set import (
    GOLD_CASES,
    GoldCase,
    evaluate,
    summarise,
)
from uadas_core.visualization.chart_recommender import ChartSuggestion, recommend_charts
from uadas_core.visualization.chart_registry import list_charts

_IDS = [case.name for case in GOLD_CASES]


def test_gold_set_has_at_least_25_uniquely_named_cases() -> None:
    assert len(GOLD_CASES) >= 25
    assert len(set(_IDS)) == len(_IDS)


@pytest.mark.parametrize("case", GOLD_CASES, ids=_IDS)
def test_case_frame_is_deterministic_and_has_the_stated_size(case: GoldCase) -> None:
    first, second = case.build(case.rows), case.build(case.rows)
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == case.rows


@pytest.mark.parametrize("case", GOLD_CASES, ids=_IDS)
def test_case_expectations_are_coherent(case: GoldCase) -> None:
    if case.expects_empty:
        assert not case.acceptable
    else:
        assert case.acceptable
    # A chart cannot be both what we want and what we forbid.
    assert not case.acceptable & case.forbidden
    frame = case.build(case.rows)
    assert case.avoid_columns <= set(frame.columns)


def test_every_named_chart_is_a_registered_chart() -> None:
    registered = set(list_charts())
    for case in GOLD_CASES:
        assert case.acceptable | case.forbidden <= registered, case.name


def test_evaluate_runs_the_current_recommender_over_every_case() -> None:
    results = evaluate(lambda frame, k: recommend_charts(frame, max_suggestions=k))
    assert [r.name for r in results] == _IDS
    summary = summarise(results)
    assert summary["cases"] == len(GOLD_CASES)
    assert 0.0 <= summary["top3_hit_rate"] <= 1.0


def test_evaluate_records_a_crash_and_carries_on() -> None:
    def boom(frame: pd.DataFrame, k: int) -> list[ChartSuggestion]:
        raise RuntimeError("tenant data in this message must never be echoed")

    results = evaluate(boom)
    assert len(results) == len(GOLD_CASES)
    assert {r.error for r in results} == {"RuntimeError"}
    assert summarise(results)["crashes"] == len(GOLD_CASES)


def test_evaluate_flags_a_bound_avoided_column_and_a_wrong_nonempty_answer() -> None:
    def bad(frame: pd.DataFrame, k: int) -> list[ChartSuggestion]:
        columns = list(frame.columns[:1]) or ["x"]
        return [ChartSuggestion("pie", columns, "r", 1.0)]

    by_name = {r.name: r for r in evaluate(bad)}
    # zero_rows expects no suggestion at all, so any suggestion is wrong.
    assert by_name["zero_rows"].empty_ok is False
    # numeric_id_trap's first column is order_id, which must never be bound.
    assert by_name["numeric_id_trap"].avoided_bound == ("order_id",)
