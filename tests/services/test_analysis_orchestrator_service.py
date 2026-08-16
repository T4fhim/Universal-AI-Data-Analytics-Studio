# File: tests/services/test_analysis_orchestrator_service.py
"""Tests for src.services.analysis_orchestrator_service.AnalysisOrchestratorService.

Covers the stage-by-stage API the milestone plan requires
(propose_next_stage()/run_stage()), that run_stage dispatches through
the real src.ai.tool_registry tools (no new statistics invented — see
that module's own docstring), that Dataset/Figure results get
registered into WorkspaceService the same way AssistantService does,
and that reproduce() replays a logged pipeline against fresh tool
calls in order.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.analysis.explanation import Explanation
from src.core.exceptions import ServiceError
from src.services.analysis_orchestrator_service import (
    AnalysisLog,
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.workspace_service import Dataset, WorkspaceService


def _make_dataset() -> Dataset:
    return Dataset(
        name="sales",
        dataframe=pd.DataFrame(
            {
                "region": ["east", "west", None, "east", "west"],
                "revenue": [100, 200, 150, 120, None],
            }
        ),
        source_format="csv",
    )


@pytest.fixture()
def workspace() -> WorkspaceService:
    return WorkspaceService()


@pytest.fixture()
def orchestrator(workspace: WorkspaceService) -> AnalysisOrchestratorService:
    return AnalysisOrchestratorService(workspace)


@pytest.fixture()
def dataset(workspace: WorkspaceService) -> Dataset:
    ds = _make_dataset()
    workspace.add_dataset(ds)
    return ds


def test_propose_next_stage_starts_with_understand(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    proposal = orchestrator.propose_next_stage(dataset.dataset_id)
    assert proposal.stage == PipelineStage.UNDERSTAND
    assert proposal.rationale  # non-empty


def test_run_stage_understand_defaults_to_profile_dataset_tool(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    entry = orchestrator.run_stage(dataset.dataset_id, PipelineStage.UNDERSTAND)

    assert entry.tool_name == "profile_dataset"
    assert entry.outputs["row_count"] == 5
    assert entry.outputs["column_count"] == 2


def test_propose_next_stage_advances_after_understand_logged(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    orchestrator.run_stage(dataset.dataset_id, PipelineStage.UNDERSTAND)

    proposal = orchestrator.propose_next_stage(dataset.dataset_id)
    assert proposal.stage == PipelineStage.CLEAN


def test_run_stage_clean_registers_new_dataset_and_returns_its_id(
    orchestrator: AnalysisOrchestratorService,
    dataset: Dataset,
    workspace: WorkspaceService,
) -> None:
    entry = orchestrator.run_stage(
        dataset.dataset_id,
        PipelineStage.CLEAN,
        tool_name="drop_missing_values",
    )

    assert "new_dataset_id" in entry.outputs
    new_id = entry.outputs["new_dataset_id"]
    cleaned = workspace.get_dataset(new_id)
    assert cleaned.row_count == 3  # 2 rows had a missing value
    assert cleaned.parent_dataset_id == dataset.dataset_id


def test_run_stage_visualize_registers_visualization(
    orchestrator: AnalysisOrchestratorService,
    dataset: Dataset,
    workspace: WorkspaceService,
) -> None:
    entry = orchestrator.run_stage(
        dataset.dataset_id,
        PipelineStage.VISUALIZE,
        tool_name="build_chart",
        tool_kwargs={"chart_type": "bar", "category_column": "region"},
    )

    assert "visualization_id" in entry.outputs
    viz = workspace.get_visualization(entry.outputs["visualization_id"])
    assert viz.dataset_id == dataset.dataset_id


def test_run_stage_explain_requires_explanation(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    with pytest.raises(ServiceError, match="requires an explanation"):
        orchestrator.run_stage(dataset.dataset_id, PipelineStage.EXPLAIN)


def test_run_stage_explain_records_explanation_without_running_a_tool(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    explanation = Explanation(
        what="Revenue varies by region.", why_it_matters="Guides budget allocation."
    )

    entry = orchestrator.run_stage(
        dataset.dataset_id, PipelineStage.EXPLAIN, explanation=explanation
    )

    assert entry.tool_name is None
    assert entry.explanation["what"] == "Revenue varies by region."


def test_run_stage_rejects_report_and_reproduce_stages(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    with pytest.raises(ServiceError, match="not run through run_stage"):
        orchestrator.run_stage(dataset.dataset_id, PipelineStage.REPORT)
    with pytest.raises(ServiceError, match="not run through run_stage"):
        orchestrator.run_stage(dataset.dataset_id, PipelineStage.REPRODUCE)


def test_run_stage_requires_tool_name_for_non_special_stages(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    with pytest.raises(ServiceError, match="requires tool_name"):
        orchestrator.run_stage(dataset.dataset_id, PipelineStage.ANALYZE)


def test_run_stage_unknown_dataset_id_raises(
    orchestrator: AnalysisOrchestratorService,
) -> None:
    with pytest.raises(ServiceError, match="No dataset"):
        orchestrator.run_stage("does-not-exist", PipelineStage.UNDERSTAND)


def test_propose_next_stage_reaches_report_after_every_auto_stage_logged(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    orchestrator.run_stage(dataset.dataset_id, PipelineStage.UNDERSTAND)
    orchestrator.run_stage(
        dataset.dataset_id, PipelineStage.CLEAN, tool_name="drop_missing_values"
    )
    orchestrator.run_stage(
        dataset.dataset_id,
        PipelineStage.EXPLORE,
        tool_name="aggregate",
        tool_kwargs={
            "group_by": ["region"],
            "agg_column": "revenue",
            "agg_function": "mean",
        },
    )
    orchestrator.run_stage(
        dataset.dataset_id, PipelineStage.ANALYZE, tool_name="profile_dataset"
    )
    orchestrator.run_stage(
        dataset.dataset_id,
        PipelineStage.VISUALIZE,
        tool_name="build_chart",
        tool_kwargs={"chart_type": "histogram", "column": "revenue"},
    )
    orchestrator.run_stage(
        dataset.dataset_id,
        PipelineStage.PREDICT,
        tool_name="profile_dataset",
    )
    orchestrator.run_stage(
        dataset.dataset_id, PipelineStage.EXPLAIN, explanation=Explanation(what="done")
    )

    proposal = orchestrator.propose_next_stage(dataset.dataset_id)
    assert proposal.stage == PipelineStage.REPORT


def test_reproduce_replays_logged_tool_calls_in_order(
    orchestrator: AnalysisOrchestratorService,
    dataset: Dataset,
    workspace: WorkspaceService,
) -> None:
    orchestrator.run_stage(dataset.dataset_id, PipelineStage.UNDERSTAND)
    orchestrator.run_stage(
        dataset.dataset_id, PipelineStage.CLEAN, tool_name="drop_missing_values"
    )

    replayed = orchestrator.reproduce(dataset.dataset_id)

    # Two tool-call entries were logged (UNDERSTAND, CLEAN); both replayed.
    assert len(replayed) == 2
    assert replayed[0].tool_name == "profile_dataset"
    assert replayed[1].tool_name == "drop_missing_values"
    # The replayed CLEAN stage produced a *new* derived dataset distinct
    # from the one created during the original run.
    original_clean_id = (
        orchestrator.get_log(dataset.dataset_id).entries[1].outputs["new_dataset_id"]
    )
    assert replayed[1].outputs["new_dataset_id"] != original_clean_id


def test_reproduce_unknown_dataset_id_raises(
    orchestrator: AnalysisOrchestratorService,
) -> None:
    with pytest.raises(ServiceError, match="No analysis log"):
        orchestrator.reproduce("does-not-exist")


def test_analysis_log_round_trips_through_to_dict_from_dict(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    orchestrator.run_stage(dataset.dataset_id, PipelineStage.UNDERSTAND)
    log = orchestrator.get_log(dataset.dataset_id)

    restored = AnalysisLog.from_dict(log.to_dict())

    assert restored.dataset_id == log.dataset_id
    assert len(restored.entries) == 1
    assert restored.entries[0].stage == PipelineStage.UNDERSTAND
    assert restored.entries[0].tool_name == "profile_dataset"


def test_load_log_installs_a_restored_log(
    orchestrator: AnalysisOrchestratorService, dataset: Dataset
) -> None:
    restored = AnalysisLog(dataset_id=dataset.dataset_id)
    restored.entries.append(
        orchestrator.run_stage(dataset.dataset_id, PipelineStage.UNDERSTAND)
    )
    # A fresh orchestrator has no memory of the above run.
    fresh = AnalysisOrchestratorService(WorkspaceService())
    fresh.load_log(restored)

    assert fresh.get_log(dataset.dataset_id).completed_stages() == {
        PipelineStage.UNDERSTAND
    }
