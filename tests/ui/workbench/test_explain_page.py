# File: tests/ui/workbench/test_explain_page.py
"""Tests for ExplainPage -- the EXPLAIN stage's ExplanationPanel-only page."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.analysis.explanation import Explanation
from src.core.expertise_level import ExpertiseLevel
from src.ui.workbench.pages.explain_page import ExplainPage


def test_explain_page_defaults_to_an_empty_explanation_with_no_ai(
    qapp: QApplication,
) -> None:
    page = ExplainPage()

    assert page.explanation_panel._labels["what"].text() == "(not provided)"
    assert "No AI-generated explanation" in page._result_label.text()


def test_show_explanation_renders_a_real_explanation(qapp: QApplication) -> None:
    page = ExplainPage()
    explanation = Explanation(what="The two groups differ significantly.")

    page.show_explanation(explanation, ExpertiseLevel.BEGINNER)

    assert (
        page.explanation_panel._labels["what"].text()
        == "The two groups differ significantly."
    )
    assert page._result_label.text() == "The two groups differ significantly."
    assert page.explanation_panel.is_expanded("what") is True
