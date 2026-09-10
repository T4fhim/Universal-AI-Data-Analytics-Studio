# File: tests/provenance/test_dag.py
"""`analysis_logs_to_dag` reshape rules, checked against the §C-2 fixture catalog.

Pins spec §1: one dataset node per mentioned id, one transform edge per
dataset-producing entry (keyed on ``"new_dataset_id" in outputs``, never on
``stage``), one artifact node per non-producing entry, missing metadata
synthesized as ``partial`` rather than raised, and a ``parent_dataset_id``
cycle rejected at the loader boundary.
"""

from __future__ import annotations

import pytest

from tests.provenance.conftest import datasets_for
from uadas_core.core.exceptions import ServiceError
from uadas_core.provenance.dag import DatasetMeta, analysis_logs_to_dag
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisLog,
    AnalysisLogEntry,
    PipelineStage,
)


def test_nodes_cover_every_mentioned_dataset_id(analysis_log_set):
    dag = analysis_logs_to_dag(analysis_log_set, datasets_for(analysis_log_set))
    mentioned = {log.dataset_id for log in analysis_log_set} | {
        e.outputs["new_dataset_id"]
        for log in analysis_log_set
        for e in log.entries
        if "new_dataset_id" in e.outputs
    }
    assert {n.dataset_id for n in dag.nodes} == mentioned


def test_one_edge_per_clean_entry_from_the_enclosing_log(analysis_log_set):
    dag = analysis_logs_to_dag(analysis_log_set, datasets_for(analysis_log_set))
    expected = {
        (log.dataset_id, e.outputs["new_dataset_id"])
        for log in analysis_log_set
        for e in log.entries
        if "new_dataset_id" in e.outputs
    }
    assert {(e.from_dataset_id, e.to_dataset_id) for e in dag.edges} == expected


def test_every_non_clean_entry_is_an_artifact_node(analysis_log_set):
    dag = analysis_logs_to_dag(analysis_log_set, datasets_for(analysis_log_set))
    expected = {
        (log.dataset_id, i)
        for log in analysis_log_set
        for i, e in enumerate(log.entries)
        if "new_dataset_id" not in e.outputs
    }
    assert {(a.dataset_id, a.entry_index) for a in dag.artifacts} == expected


def test_missing_meta_is_synthesized_partial_not_raised():
    log = AnalysisLog(
        "root",
        [
            AnalysisLogEntry(
                PipelineStage.CLEAN,
                "drop_missing_values",
                {},
                {"new_dataset_id": "child", "derivation_description": "x"},
                None,
                "2026-09-07T14:32:20Z",
            )
        ],
    )
    dag = analysis_logs_to_dag([log], {})
    assert {n.dataset_id for n in dag.nodes} == {"root", "child"}
    assert all(n.meta.partial for n in dag.nodes)


def test_a_dataset_id_cycle_raises_serviceerror():
    metas = {
        "a": DatasetMeta("a", "a", 1, 1, "csv", "b"),
        "b": DatasetMeta("b", "b", 1, 1, "csv", "a"),
    }
    with pytest.raises(ServiceError, match="cycle"):
        analysis_logs_to_dag([AnalysisLog("a"), AnalysisLog("b")], metas)


def test_stage_is_never_the_edge_predicate():
    # An ANALYZE entry that produced a dataset is still an edge, not an artifact.
    log = AnalysisLog(
        "root",
        [
            AnalysisLogEntry(
                PipelineStage.ANALYZE,
                "drop_duplicates",
                {},
                {"new_dataset_id": "child", "derivation_description": "x"},
                None,
                "2026-09-07T14:32:20Z",
            )
        ],
    )
    dag = analysis_logs_to_dag([log], {})
    assert len(dag.edges) == 1 and not dag.artifacts
