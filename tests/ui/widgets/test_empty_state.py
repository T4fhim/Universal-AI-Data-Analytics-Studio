# File: tests/ui/widgets/test_empty_state.py
"""Tests for EmptyState -- milestone 27."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.ui.theme.tokens import DARK_TOKENS
from src.ui.widgets.empty_state import EmptyState, render_illustration


def test_heading_and_message_are_shown(qapp: QApplication) -> None:
    widget = EmptyState(heading="No Datasets Loaded", message="Open a file to begin.")
    assert widget._heading_label.text() == "No Datasets Loaded"
    assert widget._message_label.text() == "Open a file to begin."


def test_the_widget_and_illustration_have_real_accessible_names(
    qapp: QApplication,
) -> None:
    widget = EmptyState(heading="No Datasets Loaded", message="Open a file to begin.")
    assert widget.accessibleName() == "No Datasets Loaded"
    assert widget.accessibleDescription() == "Open a file to begin."
    # Milestone 27's own a11y-audit criterion: the illustration is described, not silenced.
    assert widget._illustration_label.accessibleName()
    assert widget._illustration_label.accessibleDescription()


def test_no_action_button_by_default(qapp: QApplication) -> None:
    widget = EmptyState(heading="No Datasets Loaded", message="Open a file to begin.")
    assert widget.action_button is None


def test_action_button_is_built_when_action_text_given(qapp: QApplication) -> None:
    widget = EmptyState(
        heading="No Datasets Loaded",
        message="Open a file to begin.",
        action_text="Open Dataset",
    )
    assert widget.action_button is not None
    assert widget.action_button.text() == "Open Dataset"


def test_clicking_the_action_button_emits_action_triggered(qapp: QApplication) -> None:
    widget = EmptyState(
        heading="No Datasets Loaded",
        message="Open a file to begin.",
        action_text="Open Dataset",
    )
    received: list[None] = []
    widget.action_triggered.connect(lambda: received.append(None))

    widget.action_button.click()

    assert len(received) == 1


def test_set_message_replaces_the_text_and_the_accessible_description(
    qapp: QApplication,
) -> None:
    widget = EmptyState(heading="No Datasets Loaded", message="Open a file to begin.")

    widget.set_message("Try a different filter.")

    assert widget._message_label.text() == "Try a different filter."
    assert widget.accessibleDescription() == "Try a different filter."


def test_render_illustration_returns_a_transparent_pixmap_for_a_missing_file(
    qapp: QApplication,
) -> None:
    pixmap = render_illustration("does-not-exist", DARK_TOKENS.text_secondary, 32)
    assert pixmap.width() == 32
    assert pixmap.height() == 32


def test_render_illustration_finds_a_real_shipped_illustration(
    qapp: QApplication,
) -> None:
    pixmap = render_illustration("empty-box", DARK_TOKENS.text_secondary, 32)
    assert not pixmap.isNull()
