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


# Whole-branch diagnosis (2026-09-10): Dag.roots() is a new public method with
# no direct test -- it would pass as `return []` or `return self.nodes`.


def _clean_entry(new_id: str) -> AnalysisLogEntry:
    return AnalysisLogEntry(
        PipelineStage.CLEAN,
        "drop_missing_values",
        {},
        {"new_dataset_id": new_id, "derivation_description": "x"},
        None,
        "2026-09-07T14:32:20Z",
    )


def test_roots_is_the_single_chain_start_for_a_two_log_set(analysis_log_set):
    dag = analysis_logs_to_dag(analysis_log_set, datasets_for(analysis_log_set))
    root_ids = {n.dataset_id for n in dag.roots()}
    edge_targets = {e.to_dataset_id for e in dag.edges}
    # a root is a node that is never an edge target
    assert root_ids == {n.dataset_id for n in dag.nodes} - edge_targets
    # and a non-empty DAG always has a start
    assert dag.nodes == [] or root_ids


def test_roots_excludes_a_derived_node_even_when_its_meta_lost_parent_dataset_id():
    # "child" is produced by an edge but its DatasetMeta has parent_dataset_id
    # None (metadata drift). roots() must still classify it non-root via the
    # edge-target check, not the parent pointer.
    log = AnalysisLog("root", [_clean_entry("child")])
    metas = {
        "root": DatasetMeta("root", "root", 1, 1, "csv", parent_dataset_id=None),
        "child": DatasetMeta("child", "child", 1, 1, "csv", parent_dataset_id=None),
    }
    dag = analysis_logs_to_dag([log], metas)
    assert {n.dataset_id for n in dag.roots()} == {"root"}
