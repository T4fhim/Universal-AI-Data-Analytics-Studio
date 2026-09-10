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

from src.ui.workbench.workbench import Workbench
from uadas_core.services.analysis_orchestrator_service import (
    AnalysisLog,
    PipelineStage,
    StageProposal,
)


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
    assert workbench.page_for(PipelineStage.PREDICT) is not None
    # UPLOAD has no page, by design -- see stage_registry.py's own docstring for why.
    assert workbench.page_for(PipelineStage.UPLOAD) is None


def test_all_pages_returns_every_constructed_page_and_each_has_a_guidance_panel(
    qapp: QApplication,
) -> None:
    """Milestone 26: Workbench.all_pages() is what main_window.py iterates to wire every
    page's GuidancePanel -- confirms both that the accessor returns everything
    page_for() can, and that every one of those pages really does carry a GuidancePanel
    (StagePage's own construction, not something a subclass has to remember to add).
    """
    from src.ui.widgets.guidance_panel import GuidancePanel

    workbench = Workbench()
    all_pages = workbench.all_pages()

    assert len(all_pages) == len(
        [s for s in PipelineStage if workbench.page_for(s) is not None]
    )
    for page in all_pages:
        assert isinstance(page.guidance_panel, GuidancePanel)


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


def test_show_stage_syncs_the_rails_current_item(qapp: QApplication) -> None:
    """Unit 6: show_stage() is the programmatic navigation path a rail click never goes
    through -- before this fix the rail's own current-item cursor (what keyboard arrow
    navigation starts from) stayed wherever a previous click left it, out of sync with
    whatever page was actually visible. See StageRail.set_current_stage's own docstring.
    """
    workbench = Workbench()
    proposal = StageProposal(stage=PipelineStage.UNDERSTAND, rationale="Profile first.")
    workbench.update_pipeline_state(
        dataset_active=True, log=AnalysisLog(dataset_id="d1"), proposal=proposal
    )

    workbench.show_stage(PipelineStage.REPORT)

    report_index = list(PipelineStage).index(PipelineStage.REPORT)
    assert workbench.stage_rail.currentRow() == report_index


def test_show_welcome_clears_the_rails_current_item(qapp: QApplication) -> None:
    workbench = Workbench()
    proposal = StageProposal(stage=PipelineStage.UNDERSTAND, rationale="Profile first.")
    workbench.update_pipeline_state(
        dataset_active=True, log=AnalysisLog(dataset_id="d1"), proposal=proposal
    )
    assert (
        workbench.stage_rail.currentItem() is not None
    )  # sanity: something was current

    workbench.update_pipeline_state(dataset_active=False, log=None, proposal=None)

    assert workbench.stage_rail.currentItem() is None


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
