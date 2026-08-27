# File: tests/ui/results/test_result_card.py
"""Qt-level tests for ``ResultCard`` -- the single place this package builds widgets."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QGroupBox, QTableWidget

from src.analysis.t_test import TTestResult
from src.core.expertise_level import ExpertiseLevel
from src.ui.results.result_card import ResultCard


def _make_t_test_result() -> TTestResult:
    return TTestResult(
        statistic=2.5,
        p_value=0.013,
        degrees_of_freedom=18.0,
        group_a_mean=10.2,
        group_b_mean=8.7,
        test_type="independent",
        significant_at_0_05=True,
    )


def test_display_sets_title_and_headline(qapp: QApplication) -> None:
    card = ResultCard()
    card.display(_make_t_test_result(), ExpertiseLevel.BEGINNER)

    assert card._title_label.text() == "Independent T-Test"
    assert card._headline_label.text()


def test_display_builds_one_widget_per_section_with_the_right_kind(
    qapp: QApplication,
) -> None:
    card = ResultCard()
    card.display(_make_t_test_result(), ExpertiseLevel.BEGINNER)

    kinds = [w.property("resultSectionKind") for w in card.section_widgets]
    assert "MetricSection" in kinds
    assert "AssumptionsSection" in kinds
    assert all(isinstance(w, QGroupBox) for w in card.section_widgets)


def test_display_gives_the_card_a_real_accessible_name(qapp: QApplication) -> None:
    card = ResultCard()
    card.display(_make_t_test_result(), ExpertiseLevel.BEGINNER)

    assert card.accessibleName() == "Result: Independent T-Test"


def test_table_section_becomes_a_real_qtablewidget(qapp: QApplication) -> None:
    from src.analysis.anova import AnovaResult

    result = AnovaResult(
        f_statistic=4.2,
        p_value=0.02,
        group_means={"a": 1.0, "b": 2.0},
        group_sizes={"a": 5, "b": 5},
        significant_at_0_05=True,
    )
    card = ResultCard()
    card.display(result, ExpertiseLevel.RESEARCHER)

    tables = [
        w
        for w in card.section_widgets
        if w.property("resultSectionKind") == "TableSection"
    ]
    assert len(tables) == 1
    table_widget = tables[0].findChild(QTableWidget)
    assert table_widget is not None
    assert table_widget.rowCount() == 2
    assert table_widget.columnCount() == 3


def test_display_twice_replaces_sections_rather_than_accumulating(
    qapp: QApplication,
) -> None:
    card = ResultCard()
    card.display(_make_t_test_result(), ExpertiseLevel.BEGINNER)
    first_count = len(card.section_widgets)

    card.display(_make_t_test_result(), ExpertiseLevel.BEGINNER)

    assert len(card.section_widgets) == first_count
