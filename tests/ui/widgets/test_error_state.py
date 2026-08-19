# File: tests/ui/widgets/test_error_state.py
"""Tests for ErrorState -- milestone 27."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.ui.widgets.error_state import ErrorState


def test_heading_and_message_are_shown(qapp: QApplication) -> None:
    widget = ErrorState(heading="Analysis Failed", message="Column 'x' not found.")
    assert widget._heading_label.text() == "Analysis Failed"
    assert widget._message_label.text() == "Column 'x' not found."


def test_the_widget_and_illustration_have_real_accessible_names(
    qapp: QApplication,
) -> None:
    widget = ErrorState(heading="Analysis Failed", message="Column 'x' not found.")
    assert widget.accessibleName() == "Analysis Failed"
    assert widget.accessibleDescription() == "Column 'x' not found."
    assert widget._illustration_label.accessibleName()
    assert widget._illustration_label.accessibleDescription()


def test_no_action_button_by_default(qapp: QApplication) -> None:
    widget = ErrorState(heading="Analysis Failed", message="Column 'x' not found.")
    assert widget.action_button is None


def test_clicking_the_action_button_emits_action_triggered(qapp: QApplication) -> None:
    widget = ErrorState(
        heading="Analysis Failed",
        message="Column 'x' not found.",
        action_text="Retry",
    )
    received: list[None] = []
    widget.action_triggered.connect(lambda: received.append(None))

    widget.action_button.click()

    assert len(received) == 1


def test_set_error_replaces_heading_and_message(qapp: QApplication) -> None:
    widget = ErrorState(heading="Analysis Failed", message="Column 'x' not found.")

    widget.set_error("Forecast Failed", "Not enough data points.")

    assert widget._heading_label.text() == "Forecast Failed"
    assert widget._message_label.text() == "Not enough data points."
    assert widget.accessibleName() == "Forecast Failed"
    assert widget.accessibleDescription() == "Not enough data points."


def test_message_text_is_selectable(qapp: QApplication) -> None:
    """A user must be able to copy a raw exception message out of the page (the same reason
    stage-page result labels are already selectable -- see StagePage's own _result_label).
    """
    from PySide6.QtCore import Qt

    widget = ErrorState(heading="Analysis Failed", message="Column 'x' not found.")
    assert (
        widget._message_label.textInteractionFlags()
        & Qt.TextInteractionFlag.TextSelectableByMouse
    )
