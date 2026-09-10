# File: tests/provenance/conftest.py
"""The §C-2 fixture catalog: every AnalysisLog *shape* the suite builds.

The design spec's C-2 acceptance gate is "every real AnalysisLog fixture
round-trips through the Recipe". No `@pytest.fixture` in the suite actually
returns an AnalysisLog — every log is built inline — so this module
reconstructs the inventory from the shapes those tests build:
1-UNDERSTAND, 1-CLEAN, 1-VISUALIZE, 1-EXPLAIN (tool_name=None + an
Explanation dict), a 7-entry single log, a two-log root/derived set, an
empty log, and a fully-populated single entry.

`ALL_ANALYSIS_LOG_FIXTURES` drives the parametrized `analysis_log_set`
fixture consumed by `test_dag.py` and `test_recipe.py`. `datasets_for` and
`_creation_order` are the helpers those tests need to state expectations
without re-deriving the reshape rules.
"""

from __future__ import annotations

import pytest

from uadas_core.analysis.explanation import Explanation
from uadas_core.provenance.dag import DatasetMeta
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisLog,
    AnalysisLogEntry,
    PipelineStage,
)

_TS = "2026-09-07T14:32:{:02d}Z".format
# Real profile_dataset output keys (verified 2026-09-10) — NO "null_counts".
_PROFILE = {
    "row_count": 5,
    "column_count": 2,
    "duplicate_row_count": 0,
    "ambiguous_type_columns": [],
    "columns": ["region", "revenue"],
}
_ROOT_ID = "550e8400-e29b-41d4-a716-446655440000"
_DERIVED_ID = "d3a8f2c1-9e4b-4a7c-b1c2-3f5e7a9b2d1c"


def _e(
    stage: str,
    tool: str | None,
    *,
    outputs: dict | None = None,
    explanation: dict | None = None,
    i: int = 0,
    inputs: dict | None = None,
) -> AnalysisLogEntry:
    return AnalysisLogEntry(
        PipelineStage(stage),
        tool,
        inputs or {},
        outputs or {},
        explanation,
        _TS(i),
    )


def _single_understand() -> list[AnalysisLog]:
    return [
        AnalysisLog(
            _ROOT_ID,
            [_e("understand", "profile_dataset", outputs=dict(_PROFILE), i=15)],
        )
    ]


def _single_clean() -> list[AnalysisLog]:
    return [
        AnalysisLog(
            _ROOT_ID,
            [
                _e(
                    "clean",
                    "drop_missing_values",
                    outputs={
                        "new_dataset_id": _DERIVED_ID,
                        "derivation_description": "Removed 2 rows with any null values",
                    },
                    i=20,
                )
            ],
        )
    ]


def _single_visualize() -> list[AnalysisLog]:
    return [
        AnalysisLog(
            _ROOT_ID,
            [
                _e(
                    "visualize",
                    "build_chart",
                    outputs={"visualization_id": "v1"},
                    inputs={"chart_type": "histogram", "column": "revenue"},
                    i=22,
                )
            ],
        )
    ]


def _single_explain() -> list[AnalysisLog]:
    return [
        AnalysisLog(
            _ROOT_ID,
            [_e("explain", None, explanation=Explanation(what="done").to_dict(), i=24)],
        )
    ]


def _seven_stage() -> list[AnalysisLog]:
    # One log with seven entries, one of which (CLEAN) produced a second
    # dataset id — mirrors tests/services/test_analysis_orchestrator_service.py
    # ::test_propose_next_stage_reaches_report… which runs every stage against
    # the same dataset_id, so the whole history lands in one log.
    return [
        AnalysisLog(
            _ROOT_ID,
            [
                _e("understand", "profile_dataset", outputs=dict(_PROFILE), i=15),
                _e(
                    "clean",
                    "drop_missing_values",
                    outputs={
                        "new_dataset_id": _DERIVED_ID,
                        "derivation_description": "Removed 2 rows with any null values",
                    },
                    i=20,
                ),
                _e(
                    "analyze",
                    "profile_dataset",
                    outputs={**_PROFILE, "row_count": 3},
                    i=25,
                ),
                _e(
                    "visualize",
                    "build_chart",
                    outputs={"visualization_id": "v1"},
                    inputs={"chart_type": "histogram", "column": "revenue"},
                    i=30,
                ),
                _e(
                    "explain",
                    None,
                    explanation=Explanation(what="done").to_dict(),
                    i=35,
                ),
                _e(
                    "understand",
                    "profile_dataset",
                    outputs={**_PROFILE, "row_count": 3},
                    i=40,
                ),
                _e(
                    "analyze",
                    "correlate",
                    outputs={"method": "pearson", "pairs": []},
                    i=45,
                ),
            ],
        )
    ]


def _two_log_set() -> list[AnalysisLog]:
    root = AnalysisLog(
        _ROOT_ID,
        [
            _e("understand", "profile_dataset", outputs=dict(_PROFILE), i=15),
            _e(
                "clean",
                "drop_missing_values",
                outputs={
                    "new_dataset_id": _DERIVED_ID,
                    "derivation_description": "Removed 2 rows with any null values",
                },
                i=20,
            ),
        ],
    )
    derived = AnalysisLog(
        _DERIVED_ID,
        [_e("analyze", "profile_dataset", outputs={**_PROFILE, "row_count": 3}, i=25)],
    )
    return [root, derived]


def _empty() -> list[AnalysisLog]:
    return [AnalysisLog("d1")]


def _fully_populated() -> list[AnalysisLog]:
    # Every AnalysisLogEntry field non-default, plus a fully-populated
    # Explanation — mirrors tests/ui/workbench/test_pages.py's inline entry.
    explanation = Explanation(
        what="Revenue and region are weakly correlated",
        why_it_matters="Rules out region as the main revenue driver",
        how_calculated="Pearson correlation coefficient",
        confidence_or_uncertainty="n=5; wide interval, treat as directional",
        assumptions=["revenue is roughly linear in the predictors"],
        limitations=["small sample", "outliers not removed"],
        alternative_approaches=["Spearman rank correlation"],
    ).to_dict()
    return [
        AnalysisLog(
            _ROOT_ID,
            [
                _e(
                    "analyze",
                    "correlate",
                    outputs={"method": "pearson", "coefficient": 0.21, "p_value": 0.73},
                    explanation=explanation,
                    inputs={"columns": ["region", "revenue"], "method": "pearson"},
                    i=50,
                )
            ],
        )
    ]


ALL_ANALYSIS_LOG_FIXTURES: list[list[AnalysisLog]] = [
    _single_understand(),
    _single_clean(),
    _single_visualize(),
    _single_explain(),
    _seven_stage(),
    _two_log_set(),
    _empty(),
    _fully_populated(),
]


def datasets_for(logs: list[AnalysisLog]) -> dict[str, DatasetMeta]:
    """A :class:`DatasetMeta` for every dataset id the log set mentions."""
    ids: set[str] = set()
    for log in logs:
        ids.add(log.dataset_id)
        for entry in log.entries:
            if "new_dataset_id" in entry.outputs:
                ids.add(entry.outputs["new_dataset_id"])
    return {
        i: DatasetMeta(i, f"ds-{i[:8]}", 5, 2, "csv", parent_dataset_id=None)
        for i in ids
    }


def _creation_order(logs: list[AnalysisLog]) -> list[AnalysisLog]:
    """Root-first linear chain of logs, following each CLEAN's ``new_dataset_id``.

    Test-side mirror of :func:`uadas_core.provenance.recipe._creation_order`;
    kept here so `test_recipe.py` can state the round-trip expectation
    without importing the implementation it is checking.
    """
    produced = {
        e.outputs["new_dataset_id"]
        for log in logs
        for e in log.entries
        if "new_dataset_id" in e.outputs
    }
    roots = [log for log in logs if log.dataset_id not in produced]
    if len(roots) != 1:
        raise AssertionError(f"expected 1 root log, found {len(roots)}")
    by_id = {log.dataset_id: log for log in logs}
    ordered: list[AnalysisLog] = []
    current: AnalysisLog | None = roots[0]
    seen: set[str] = set()
    while current is not None and current.dataset_id not in seen:
        seen.add(current.dataset_id)
        ordered.append(current)
        nxt: AnalysisLog | None = None
        for e in current.entries:
            if "new_dataset_id" in e.outputs:
                nxt = by_id.get(e.outputs["new_dataset_id"])
        current = nxt
    return ordered


@pytest.fixture(
    params=ALL_ANALYSIS_LOG_FIXTURES,
    ids=lambda f: f"{len(f)}log-{sum(len(l.entries) for l in f)}entry",
)
def analysis_log_set(request: pytest.FixtureRequest) -> list[AnalysisLog]:
    return request.param
