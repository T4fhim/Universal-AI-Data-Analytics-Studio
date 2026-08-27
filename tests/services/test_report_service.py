# File: tests/services/test_report_service.py
"""Tests for src.services.report_service.ReportService.

Covers build_report_content()'s log-to-ReportContent replay (the
milestone's "replay the log and render it" framing — see that module's
own docstring) and generate_report()'s format dispatch, using the same
WorkspaceService/AnalysisOrchestratorService fixtures as
tests/services/test_analysis_orchestrator_service.py so this test
exercises the real pipeline rather than a mocked one.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.analysis.explanation import Explanation
from src.core.exceptions import ServiceError
from src.core.expertise_level import ExpertiseLevel
from src.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.report_service import ReportService, available_formats
from src.services.workspace_service import Dataset, WorkspaceService


def _make_dataset() -> Dataset:
    return Dataset(
        name="sales",
        dataframe=pd.DataFrame(
            {"region": ["east", "west", "east"], "revenue": [100, 200, 150]}
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
def report_service(
    workspace: WorkspaceService, orchestrator: AnalysisOrchestratorService
) -> ReportService:
    return ReportService(workspace, orchestrator)


@pytest.fixture()
def dataset(workspace: WorkspaceService) -> Dataset:
    ds = _make_dataset()
    workspace.add_dataset(ds)
    return ds


def test_available_formats_matches_the_four_supported_exporters() -> None:
    assert set(available_formats()) == {"pdf", "html", "docx", "xlsx"}


def test_build_report_content_includes_dataset_summary(
    report_service: ReportService, dataset: Dataset
) -> None:
    content = report_service.build_report_content(
        dataset.dataset_id, ExpertiseLevel.ANALYST
    )

    assert content.dataset_name == "sales"
    assert content.dataset_summary["Rows"] == 3
    assert content.dataset_summary["Columns"] == 2
    assert content.title == "sales Report"


def test_build_report_content_defaults_to_empty_sections_for_unstarted_pipeline(
    report_service: ReportService, dataset: Dataset
) -> None:
    content = report_service.build_report_content(
        dataset.dataset_id, ExpertiseLevel.BEGINNER
    )

    assert content.sections == []


def test_build_report_content_replays_logged_stages_as_sections(
    report_service: ReportService,
    orchestrator: AnalysisOrchestratorService,
    dataset: Dataset,
) -> None:
    orchestrator.run_stage(dataset.dataset_id, PipelineStage.UNDERSTAND)
    orchestrator.run_stage(
        dataset.dataset_id,
        PipelineStage.EXPLAIN,
        explanation=Explanation(
            what="The dataset has 3 rows.", why_it_matters="Small sample."
        ),
    )

    content = report_service.build_report_content(
        dataset.dataset_id, ExpertiseLevel.ANALYST
    )

    assert [s.stage_label for s in content.sections] == ["Understand", "Explain"]
    understand_section, explain_section = content.sections
    assert understand_section.tool_name == "profile_dataset"
    assert explain_section.tool_name is None
    assert "The dataset has 3 rows." in explain_section.explanation_text
    assert "Why it matters: Small sample." in explain_section.explanation_text


def test_build_report_content_filters_by_included_stages(
    report_service: ReportService,
    orchestrator: AnalysisOrchestratorService,
    dataset: Dataset,
) -> None:
    orchestrator.run_stage(dataset.dataset_id, PipelineStage.UNDERSTAND)
    orchestrator.run_stage(
        dataset.dataset_id,
        PipelineStage.EXPLAIN,
        explanation=Explanation(what="done"),
    )

    content = report_service.build_report_content(
        dataset.dataset_id,
        ExpertiseLevel.ANALYST,
        included_stages={PipelineStage.UNDERSTAND},
    )

    assert [s.stage_label for s in content.sections] == ["Understand"]


def test_build_report_content_unknown_dataset_raises(
    report_service: ReportService,
) -> None:
    with pytest.raises(ServiceError):
        report_service.build_report_content("does-not-exist", ExpertiseLevel.ANALYST)


def test_generate_report_dispatches_to_the_right_exporter(
    report_service: ReportService, dataset: Dataset, tmp_path: Path
) -> None:
    output_path = tmp_path / "report.html"

    result = report_service.generate_report(
        dataset.dataset_id, output_path, "html", ExpertiseLevel.ANALYST
    )

    assert result == output_path
    assert output_path.exists()
    assert "sales Report" in output_path.read_text(encoding="utf-8")


def test_generate_report_unknown_format_raises(
    report_service: ReportService, dataset: Dataset, tmp_path: Path
) -> None:
    with pytest.raises(ServiceError):
        report_service.generate_report(
            dataset.dataset_id, tmp_path / "report.xyz", "xyz", ExpertiseLevel.ANALYST
        )
