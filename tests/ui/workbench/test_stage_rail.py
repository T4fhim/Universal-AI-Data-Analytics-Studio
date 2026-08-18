# File: tests/ui/workbench/test_stage_rail.py
"""Tests for StageRail: real accessible name, per-stage status, and click-to-select."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.services.analysis_orchestrator_service import PipelineStage
from src.ui.workbench.stage_rail import StageRail


def test_rail_has_one_item_per_pipeline_stage(qapp: QApplication) -> None:
    rail = StageRail()
    assert rail.count() == len(list(PipelineStage))


def test_rail_has_a_real_accessible_name(qapp: QApplication) -> None:
    rail = StageRail()
    assert rail.accessibleName() == "Pipeline stage rail"
    assert rail.accessibleDescription()


def test_every_stage_starts_pending(qapp: QApplication) -> None:
    rail = StageRail()
    for stage in PipelineStage:
        assert rail.status_for(stage) == "pending"


def test_update_state_reflects_real_orchestrator_state(qapp: QApplication) -> None:
    """The M20 acceptance criterion: UPLOAD complete, UNDERSTAND proposed."""
    rail = StageRail()
    rail.update_state(
        completed={PipelineStage.UPLOAD}, proposed=PipelineStage.UNDERSTAND
    )

    assert rail.status_for(PipelineStage.UPLOAD) == "complete"
    assert rail.status_for(PipelineStage.UNDERSTAND) == "proposed"
    assert rail.status_for(PipelineStage.CLEAN) == "pending"


def test_status_prefix_is_visible_in_the_item_text_not_color_only(
    qapp: QApplication,
) -> None:
    """WCAG 1.4.1: status must be legible from text alone, not hue alone."""
    rail = StageRail()
    rail.update_state(completed={PipelineStage.UPLOAD}, proposed=None)
    item = rail.item(0)
    assert item.text().startswith("✓")


def test_clicking_an_item_emits_a_real_pipeline_stage_not_a_plain_string(
    qapp: QApplication,
) -> None:
    rail = StageRail()
    received: list[object] = []
    rail.stage_selected.connect(received.append)

    understand_index = list(PipelineStage).index(PipelineStage.UNDERSTAND)
    item = rail.item(understand_index)
    rail.itemClicked.emit(item)

    assert received == [PipelineStage.UNDERSTAND]
    assert isinstance(received[0], PipelineStage)
