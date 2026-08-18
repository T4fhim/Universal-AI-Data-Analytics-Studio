# File: tests/ui/workbench/test_stage_registry.py
"""Tests for the stage_registry module -- mirrors chart_registry's own test shape."""

from __future__ import annotations

import pytest

from src.core.exceptions import ServiceError
from src.services.analysis_orchestrator_service import PipelineStage
from src.ui.workbench import stage_page, stage_registry


def test_builtin_stages_are_registered() -> None:
    registered = stage_registry.list_registered_stages()
    assert PipelineStage.UNDERSTAND in registered
    assert PipelineStage.CLEAN in registered
    assert PipelineStage.EXPLORE in registered
    assert PipelineStage.ANALYZE in registered
    assert PipelineStage.EXPLAIN in registered
    assert PipelineStage.REPORT in registered
    assert PipelineStage.REPRODUCE in registered


def test_get_stage_page_class_returns_none_for_an_unregistered_stage() -> None:
    # VISUALIZE has no page yet (milestone 24's own scope) -- CLEAN gained one in milestone 23.
    assert stage_registry.get_stage_page_class(PipelineStage.VISUALIZE) is None


def test_register_stage_page_rejects_a_duplicate_stage() -> None:
    with pytest.raises(ServiceError):
        stage_registry.register_stage_page(
            PipelineStage.UNDERSTAND,
            stage_registry.get_stage_page_class(PipelineStage.UNDERSTAND),
        )


def test_register_stage_page_rejects_a_mismatched_page_class() -> None:
    class _WrongStagePage(stage_page.StagePage):
        stage = PipelineStage.CLEAN
        help_anchor = "pipeline.clean"

    with pytest.raises(ServiceError):
        stage_registry.register_stage_page(PipelineStage.EXPLORE, _WrongStagePage)


def test_unregister_then_reregister_a_stage_page_round_trips() -> None:
    page_class = stage_registry.get_stage_page_class(PipelineStage.REPRODUCE)
    assert page_class is not None
    try:
        stage_registry.unregister_stage_page(PipelineStage.REPRODUCE)
        assert stage_registry.get_stage_page_class(PipelineStage.REPRODUCE) is None
    finally:
        stage_registry.register_stage_page(PipelineStage.REPRODUCE, page_class)
    assert stage_registry.get_stage_page_class(PipelineStage.REPRODUCE) is page_class
