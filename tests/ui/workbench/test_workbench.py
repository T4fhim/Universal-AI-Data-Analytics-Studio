# File: tests/ui/workbench/test_workbench.py
"""Tests for Workbench: central-widget page transitions and pipeline-state rendering.

Backs milestone 20's acceptance criteria:
1. Workbench replaces WelcomeWidget as the (non-permanent) central widget; opening a dataset
   transitions the center pane.
2. The stage rail reflects real orchestrator state: UPLOAD complete, UNDERSTAND proposed, with
   the actual StageProposal.rationale displayed.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.services.analysis_orchestrator_service import (
    AnalysisLog,
    PipelineStage,
    StageProposal,
)
from src.ui.workbench.workbench import Workbench


def test_workbench_starts_on_the_welcome_page(qapp: QApplication) -> None:
    workbench = Workbench()
    assert workbench.stack.currentWidget() is workbench.welcome_page


def test_workbench_has_a_page_for_every_registered_stage(qapp: QApplication) -> None:
    workbench = Workbench()
    assert workbench.page_for(PipelineStage.UNDERSTAND) is not None
    assert workbench.page_for(PipelineStage.CLEAN) is not None
    assert workbench.page_for(PipelineStage.REPORT) is not None
    assert workbench.page_for(PipelineStage.REPRODUCE) is not None
    assert workbench.page_for(PipelineStage.VISUALIZE) is not None
    # PREDICT has no page yet (milestone 25's own scope) -- returns None, not a crash.
    assert workbench.page_for(PipelineStage.PREDICT) is None


def test_opening_a_dataset_transitions_the_center_pane_off_welcome(
    qapp: QApplication,
) -> None:
    workbench = Workbench()
    proposal = StageProposal(stage=PipelineStage.UNDERSTAND, rationale="Profile first.")

    workbench.update_pipeline_state(
        dataset_active=True, log=AnalysisLog(dataset_id="d1"), proposal=proposal
    )

    assert workbench.stack.currentWidget() is not workbench.welcome_page
    assert workbench.stack.currentWidget() is workbench.page_for(
        PipelineStage.UNDERSTAND
    )


def test_no_active_dataset_shows_the_welcome_page_again(qapp: QApplication) -> None:
    workbench = Workbench()
    proposal = StageProposal(stage=PipelineStage.UNDERSTAND, rationale="Profile first.")
    workbench.update_pipeline_state(
        dataset_active=True, log=AnalysisLog(dataset_id="d1"), proposal=proposal
    )

    workbench.update_pipeline_state(dataset_active=False, log=None, proposal=None)

    assert workbench.stack.currentWidget() is workbench.welcome_page


def test_stage_rail_reflects_upload_complete_and_understand_proposed(
    qapp: QApplication,
) -> None:
    workbench = Workbench()
    proposal = StageProposal(
        stage=PipelineStage.UNDERSTAND, rationale="Profile the dataset first."
    )

    workbench.update_pipeline_state(
        dataset_active=True, log=AnalysisLog(dataset_id="d1"), proposal=proposal
    )

    assert workbench.stage_rail.status_for(PipelineStage.UPLOAD) == "complete"
    assert workbench.stage_rail.status_for(PipelineStage.UNDERSTAND) == "proposed"


def test_the_real_stage_proposal_rationale_reaches_the_guidance_card(
    qapp: QApplication,
) -> None:
    workbench = Workbench()
    proposal = StageProposal(
        stage=PipelineStage.UNDERSTAND,
        rationale="Profile the dataset first -- a very specific rationale string.",
    )

    workbench.update_pipeline_state(
        dataset_active=True, log=AnalysisLog(dataset_id="d1"), proposal=proposal
    )

    understand_page = workbench.page_for(PipelineStage.UNDERSTAND)
    assert understand_page is not None
    assert (
        understand_page._guidance_label.text()
        == "Profile the dataset first -- a very specific rationale string."
    )


def test_manual_navigation_is_not_yanked_back_by_a_later_refresh(
    qapp: QApplication,
) -> None:
    """The free-roam escape hatch: once off welcome, a state refresh must not force navigation."""
    workbench = Workbench()
    proposal = StageProposal(stage=PipelineStage.UNDERSTAND, rationale="Profile first.")
    workbench.update_pipeline_state(
        dataset_active=True, log=AnalysisLog(dataset_id="d1"), proposal=proposal
    )

    # User manually navigates to Report.
    workbench.show_stage(PipelineStage.REPORT)
    assert workbench.stack.currentWidget() is workbench.page_for(PipelineStage.REPORT)

    # A later, unrelated pipeline-state refresh must not move them back to Understand.
    workbench.update_pipeline_state(
        dataset_active=True, log=AnalysisLog(dataset_id="d1"), proposal=proposal
    )
    assert workbench.stack.currentWidget() is workbench.page_for(PipelineStage.REPORT)
