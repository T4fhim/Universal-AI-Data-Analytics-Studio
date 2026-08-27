# File: tests/ui/workbench/test_pages.py
"""Tests for the concrete StagePage subclasses and the welcome page.

Covers milestone 20's acceptance criterion 3's UI half (the Run button emits a request; the
controller call itself, and the resulting AnalysisLogEntry, are covered by
``tests/ui/controllers/test_pipeline_controller.py``) and acceptance criterion 6 (a real
accessible name on every new interactive widget).
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.services.analysis_orchestrator_service import (
    AnalysisLog,
    AnalysisLogEntry,
    PipelineStage,
)
from src.ui.workbench.pages.report_page import ReportPage
from src.ui.workbench.pages.reproduce_page import ReproducePage
from src.ui.workbench.pages.understand_page import UnderstandPage
from src.ui.workbench.pages.welcome_page import WelcomePage
from tests.ui.qt_helpers import click


def test_understand_page_run_button_has_a_real_accessible_name(
    qapp: QApplication,
) -> None:
    page = UnderstandPage()
    assert page.run_button.accessibleName() == "Run Understand stage"
    assert page.run_button.accessibleDescription()


def test_clicking_run_emits_run_requested(qapp: QApplication) -> None:
    page = UnderstandPage()
    received: list[None] = []
    page.run_requested.connect(lambda: received.append(None))

    click(page.run_button)

    assert len(received) == 1


def test_understand_page_shows_a_real_profile_summary(qapp: QApplication) -> None:
    page = UnderstandPage()
    outputs = {
        "row_count": 1204,
        "column_count": 8,
        "duplicate_row_count": 3,
        "ambiguous_type_columns": ["maybe_date"],
    }

    page.show_profile_summary(outputs)

    text = page._result_label.text()
    assert "1,204" in text
    assert "8 columns" in text
    assert "maybe_date" in text


def test_report_page_generate_button_has_a_real_accessible_name(
    qapp: QApplication,
) -> None:
    page = ReportPage()
    assert page.generate_button.accessibleName() == "Generate report"


def test_report_page_update_log_reflects_recorded_entries(qapp: QApplication) -> None:
    page = ReportPage()
    log = AnalysisLog(
        dataset_id="d1",
        entries=[
            AnalysisLogEntry(
                stage=PipelineStage.UNDERSTAND,
                tool_name="profile_dataset",
                inputs={},
                outputs={},
                explanation=None,
                timestamp="2026-01-01T00:00:00+00:00",
            )
        ],
    )

    page.update_log(log)

    assert "1 stage(s)" in page._result_label.text()
    assert "understand" in page._result_label.text()


def test_report_page_update_log_handles_no_active_dataset(qapp: QApplication) -> None:
    page = ReportPage()
    page.update_log(None)
    assert "No stages recorded" in page._result_label.text()


def test_reproduce_page_button_has_a_real_accessible_name(qapp: QApplication) -> None:
    page = ReproducePage()
    assert page.reproduce_button.accessibleName() == "Reproduce recorded analysis"


def test_clicking_reproduce_emits_reproduce_requested(qapp: QApplication) -> None:
    page = ReproducePage()
    received: list[None] = []
    page.reproduce_requested.connect(lambda: received.append(None))

    click(page.reproduce_button)

    assert len(received) == 1


def test_welcome_page_exposes_the_same_buttons_as_welcome_widget(
    qapp: QApplication,
) -> None:
    page = WelcomePage()
    assert page.button_new_project.text() == "New Project"
    assert page.button_open_project.text() == "Open Project..."
