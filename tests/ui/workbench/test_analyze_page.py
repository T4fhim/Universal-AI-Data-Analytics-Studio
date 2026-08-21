# File: tests/ui/workbench/test_analyze_page.py
"""Tests for AnalyzePage -- covers milestone 22's acceptance criterion 1 end to end.

"Running a t-test from the Analyze page renders a ResultCard with statistic, p-value, and an
AssumptionsSection -- with no API key configured." No test in this file imports, patches, or
otherwise touches :mod:`src.ai.llm_provider`/``AssistantService`` -- proving the "no API key
configured" half is not merely untested but structurally impossible to depend on here: nothing
on this path ever constructs an LLM provider (see
:mod:`src.ui.workbench.pages.analyze_page`'s own docstring for why it calls
:mod:`src.analysis` functions directly).
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication

from src.core.expertise_level import ExpertiseLevel
from src.services.workspace_service import Dataset
from src.ui.workbench.pages.analyze_page import AnalyzePage


def _make_dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "value": [10.0, 11.0, 9.5, 10.5, 20.0, 21.0, 19.5, 20.5],
            "group": ["A", "A", "A", "A", "B", "B", "B", "B"],
        }
    )
    return Dataset(name="ttest-demo", dataframe=frame, source_format="csv")


def test_running_a_t_test_from_the_analyze_page_renders_a_result_card_end_to_end(
    qapp: QApplication,
) -> None:
    """Milestone 22 acceptance criterion 1, exercised end to end: constructs a real
    AnalyzePage, hands it a real Dataset (the same set_dataset() call main_window.py's
    _refresh_workbench makes), runs the real independent_t_test tool with real parameters, and
    asserts the resulting ResultCard genuinely contains a statistic, a p-value, and an
    AssumptionsSection -- not a mock, not a stub result.
    """
    page = AnalyzePage()
    dataset = _make_dataset()
    page.set_dataset(dataset)

    page.run_analysis(
        dataset,
        "independent_t_test",
        {
            "value_column": "value",
            "group_column": "group",
            "group_a": "A",
            "group_b": "B",
        },
        ExpertiseLevel.BEGINNER,
    )

    kinds = [w.property("resultSectionKind") for w in page.result_card.section_widgets]
    assert "MetricSection" in kinds  # statistic and p-value are both MetricSections
    assert "AssumptionsSection" in kinds
    assert page.result_card._title_label.text() == "Independent T-Test"

    # Both the T-Statistic and P-Value metrics must be present as group-box titles.
    section_titles = {w.title() for w in page.result_card.section_widgets}
    assert "T-Statistic" in section_titles
    assert "P-Value" in section_titles


def test_analyze_page_run_button_and_combo_have_real_accessible_names(
    qapp: QApplication,
) -> None:
    page = AnalyzePage()
    assert page.run_button.accessibleName() == "Configure and run analysis"
    assert page._tool_combo.accessibleName() == "Statistical test"


def test_run_with_no_active_dataset_shows_an_informative_message(
    qapp: QApplication, block_modals
) -> None:
    page = AnalyzePage()
    page._on_run_clicked()

    assert any(call.kind == "information" for call in block_modals)


def test_run_analysis_with_unknown_tool_name_sets_an_error_result_text(
    qapp: QApplication,
) -> None:
    page = AnalyzePage()
    dataset = _make_dataset()

    page.run_analysis(dataset, "not_a_real_tool", {}, ExpertiseLevel.BEGINNER)

    assert "Unknown analysis tool" in page._result_label.text()


def test_run_analysis_reports_a_service_error_without_crashing(
    qapp: QApplication, block_modals
) -> None:
    # Milestone 27: a failed analysis is shown via the page's own in-page ErrorState now, not
    # a QMessageBox.critical -- see StagePage.show_error's own docstring.
    page = AnalyzePage()
    dataset = _make_dataset()

    # Missing required parameters triggers a real ServiceError from independent_t_test.
    page.run_analysis(dataset, "independent_t_test", {}, ExpertiseLevel.BEGINNER)

    assert not block_modals
    assert page._error_state.isHidden() is False
    assert page._error_state._heading_label.text() == "Analysis Failed"
