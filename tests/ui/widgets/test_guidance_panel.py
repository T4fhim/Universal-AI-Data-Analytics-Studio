# File: tests/ui/widgets/test_guidance_panel.py
"""Tests for GuidancePanel -- milestone 26.

Uses real :class:`~src.services.guidance_service.Suggestion` instances (not a Qt-only stand-in)
so these tests exercise the actual data shape :class:`~src.ui.main_window.MainWindow` feeds in
via :class:`~src.services.guidance_service.GuidanceService`, while constructing no
:class:`~src.services.guidance_service.GuidanceService` itself -- this is a pure display-widget
test, per :class:`GuidancePanel`'s own "holds no service reference" docstring.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.services.analysis_orchestrator_service import PipelineStage
from src.services.guidance_service import Suggestion, SuggestionCategory
from src.ui.widgets.guidance_panel import GuidancePanel


def _suggestion(
    action_id: str = "workbench.go_to_clean", title: str = "Go to Clean stage"
) -> Suggestion:
    return Suggestion(
        action_id=action_id,
        title=title,
        rationale="Because the data has real problems worth fixing.",
        category=SuggestionCategory.DATA_QUALITY,
        stage=PipelineStage.CLEAN,
        base_score=5.0,
    )


def test_a_fresh_panel_shows_the_empty_placeholder(qapp: QApplication) -> None:
    panel = GuidancePanel()
    assert panel.suggestion_count() == 0
    assert panel._list.count() == 1
    assert panel._list.item(0).text() == "No suggestions right now."


def test_the_list_has_a_real_accessible_name(qapp: QApplication) -> None:
    panel = GuidancePanel()
    assert panel._list.accessibleName() == "Suggested next steps"
    assert panel._list.accessibleDescription()


def test_set_suggestions_populates_the_list(qapp: QApplication) -> None:
    panel = GuidancePanel()
    suggestions = [
        _suggestion("workbench.go_to_clean", "Go to Clean stage"),
        _suggestion("analysis.visualize", "Create a Line chart"),
    ]

    panel.set_suggestions(suggestions)

    assert panel.suggestion_count() == 2
    assert panel._list.item(0).text().startswith("Go to Clean stage")
    assert panel._list.item(1).text().startswith("Create a Line chart")


def test_set_suggestions_with_an_empty_list_shows_the_placeholder_again(
    qapp: QApplication,
) -> None:
    panel = GuidancePanel()
    panel.set_suggestions([_suggestion()])
    assert panel.suggestion_count() == 1

    panel.set_suggestions([])

    assert panel.suggestion_count() == 0
    assert panel._list.item(0).text() == "No suggestions right now."


def test_activating_a_suggestion_emits_its_action_id(qapp: QApplication) -> None:
    panel = GuidancePanel()
    panel.set_suggestions(
        [_suggestion("workbench.go_to_visualize", "Go to Visualize stage")]
    )
    received: list[str] = []
    panel.suggestion_activated.connect(received.append)

    item = panel._list.item(0)
    panel._on_item_activated(item)

    assert received == ["workbench.go_to_visualize"]


def test_activating_the_empty_placeholder_emits_nothing(qapp: QApplication) -> None:
    panel = GuidancePanel()
    received: list[str] = []
    panel.suggestion_activated.connect(received.append)

    item = panel._list.item(0)  # the placeholder itself
    panel._on_item_activated(item)

    assert received == []


def test_item_accessible_text_includes_both_title_and_rationale(
    qapp: QApplication,
) -> None:
    from PySide6.QtCore import Qt

    panel = GuidancePanel()
    panel.set_suggestions([_suggestion()])

    item = panel._list.item(0)
    accessible_text = item.data(Qt.ItemDataRole.AccessibleTextRole)
    assert "Go to Clean stage" in accessible_text
    assert "real problems worth fixing" in accessible_text
