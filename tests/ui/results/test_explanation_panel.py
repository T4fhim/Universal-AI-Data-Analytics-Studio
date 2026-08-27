# File: tests/ui/results/test_explanation_panel.py
"""Milestone 22's acceptance criterion 4: ``ExplanationPanel`` defaults its expanded section per
``ExpertiseLevel`` exactly as A5 specifies -- a real test per level.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from src.analysis.explanation import Explanation
from src.core.expertise_level import ExpertiseLevel
from src.ui.results.explanation_panel import ExplanationPanel

_ALL_FIELDS = (
    "what",
    "why_it_matters",
    "how_calculated",
    "confidence_or_uncertainty",
    "assumptions",
    "limitations",
    "alternative_approaches",
)


def _make_explanation() -> Explanation:
    return Explanation(
        what="The two groups differ.",
        why_it_matters="This affects the business decision.",
        how_calculated="Independent t-test.",
        confidence_or_uncertainty="p = 0.01.",
        assumptions=["Independence", "Normality"],
        limitations=["Small sample"],
        alternative_approaches=["Mann-Whitney U"],
    )


def test_beginner_opens_what_and_why_it_matters(qapp: QApplication) -> None:
    panel = ExplanationPanel()
    panel.display(_make_explanation(), ExpertiseLevel.BEGINNER)

    assert panel.is_expanded("what") is True
    assert panel.is_expanded("why_it_matters") is True
    for field_name in _ALL_FIELDS:
        if field_name not in ("what", "why_it_matters"):
            assert panel.is_expanded(field_name) is False


def test_researcher_opens_assumptions_and_limitations(qapp: QApplication) -> None:
    panel = ExplanationPanel()
    panel.display(_make_explanation(), ExpertiseLevel.RESEARCHER)

    assert panel.is_expanded("assumptions") is True
    assert panel.is_expanded("limitations") is True
    for field_name in _ALL_FIELDS:
        if field_name not in ("assumptions", "limitations"):
            assert panel.is_expanded(field_name) is False


def test_engineer_opens_how_calculated(qapp: QApplication) -> None:
    panel = ExplanationPanel()
    panel.display(_make_explanation(), ExpertiseLevel.ENGINEER)

    assert panel.is_expanded("how_calculated") is True
    for field_name in _ALL_FIELDS:
        if field_name != "how_calculated":
            assert panel.is_expanded(field_name) is False


def test_student_opens_what_why_it_matters_and_how_calculated(
    qapp: QApplication,
) -> None:
    panel = ExplanationPanel()
    panel.display(_make_explanation(), ExpertiseLevel.STUDENT)

    for field_name in ("what", "why_it_matters", "how_calculated"):
        assert panel.is_expanded(field_name) is True


def test_analyst_opens_what_and_confidence(qapp: QApplication) -> None:
    panel = ExplanationPanel()
    panel.display(_make_explanation(), ExpertiseLevel.ANALYST)

    assert panel.is_expanded("what") is True
    assert panel.is_expanded("confidence_or_uncertainty") is True


def test_decision_maker_opens_what_and_why_it_matters(qapp: QApplication) -> None:
    panel = ExplanationPanel()
    panel.display(_make_explanation(), ExpertiseLevel.DECISION_MAKER)

    assert panel.is_expanded("what") is True
    assert panel.is_expanded("why_it_matters") is True


@pytest.mark.parametrize("level", list(ExpertiseLevel))
def test_every_level_has_at_least_one_expanded_field(
    qapp: QApplication, level: ExpertiseLevel
) -> None:
    panel = ExplanationPanel()
    panel.display(_make_explanation(), level)

    assert any(panel.is_expanded(f) for f in _ALL_FIELDS)


def test_field_text_is_populated_from_the_explanation(qapp: QApplication) -> None:
    panel = ExplanationPanel()
    panel.display(_make_explanation(), ExpertiseLevel.BEGINNER)

    assert panel._labels["what"].text() == "The two groups differ."
    assert "Independence" in panel._labels["assumptions"].text()


def test_missing_field_shows_a_placeholder(qapp: QApplication) -> None:
    panel = ExplanationPanel()
    panel.display(Explanation(), ExpertiseLevel.BEGINNER)

    assert panel._labels["what"].text() == "(not provided)"
