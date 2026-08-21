# File: tests/ui/widgets/test_chat_panel.py
"""Tests for ChatPanel, grounded in milestone 21's acceptance criteria.

Constructs a real ``ChatPanel`` (no service references -- see that module's own "structure
here, behavior wired by the caller" docstring) and drives its public methods directly, the same
convention ``tests/ui/results/test_result_card.py`` uses for ``ResultCard`` -- no ``qapp``-level
``MainWindow``/``DockManager`` scaffolding is needed to exercise this widget's own behavior.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QListWidget

from src.core.expertise_level import ExpertiseLevel
from src.ui.results.result_card import ResultCard
from src.ui.widgets.chat_panel import ChatPanel

# -- Criterion 2: messages are focusable, screen-reader-readable, and copyable ------------------


def test_message_list_keeps_the_default_selection_mode_not_no_selection(
    qapp: QApplication,
) -> None:
    """The named defect: setSelectionMode(NoSelection) made every message unselectable."""
    panel = ChatPanel()
    assert panel._message_list.selectionMode() != QListWidget.SelectionMode.NoSelection


def test_a_user_message_is_a_focusable_described_selectable_label(
    qapp: QApplication,
) -> None:
    panel = ChatPanel()
    panel.append_user_message("What is the average revenue?")

    widget = panel.last_message_widget()
    assert isinstance(widget, QLabel)
    assert widget.focusPolicy() != Qt.FocusPolicy.NoFocus  # keyboard-focusable
    assert widget.accessibleName() == "You said"  # real accessible name, not list noise
    assert widget.accessibleDescription() == "What is the average revenue?"
    # Copyable: real text-selection interaction flags, not a QLabel's inert default.
    flags = widget.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert flags & Qt.TextInteractionFlag.TextSelectableByKeyboard


def test_an_assistant_message_is_also_focusable_and_described(
    qapp: QApplication,
) -> None:
    panel = ChatPanel()
    panel.append_assistant_message("Average revenue is 42.")

    widget = panel.last_message_widget()
    assert isinstance(widget, QLabel)
    assert widget.accessibleName() == "Assistant replied"
    assert widget.accessibleDescription() == "Average revenue is 42."
    assert widget.focusPolicy() != Qt.FocusPolicy.NoFocus


# -- Criterion 3: non-color indicator (icon + text / accessible name) for status rows -----------


def test_tool_activity_row_conveys_state_through_text_and_accessible_name_not_color_alone(
    qapp: QApplication,
) -> None:
    panel = ChatPanel()
    panel.append_tool_activity("Ran independent_t_test.")

    widget = panel.last_message_widget()
    assert isinstance(widget, QLabel)
    # The glyph + text is real text content, readable with color entirely disabled.
    assert "⚙" in widget.text()
    assert "Ran independent_t_test." in widget.text()
    # And a distinct accessible name -- not merely "read whatever the label says."
    assert widget.accessibleName() == "Tool activity"


def test_error_row_conveys_state_through_text_and_accessible_name_not_color_alone(
    qapp: QApplication,
) -> None:
    panel = ChatPanel()
    panel.append_error_message("Unknown tool: not_a_real_tool")

    widget = panel.last_message_widget()
    assert isinstance(widget, QLabel)
    assert "⚠" in widget.text()
    assert "Unknown tool: not_a_real_tool" in widget.text()
    assert widget.accessibleName() == "Error"


def test_tool_activity_and_error_rows_use_no_foreground_color_override(
    qapp: QApplication,
) -> None:
    """The removed half of the original defect: color is no longer the (redundant) second
    signal -- a QLabel with no explicit foreground role override inherits the theme's normal
    text color, rather than a row-specific gray/red QListWidgetItem.setForeground() call.
    """
    panel = ChatPanel()
    panel.append_tool_activity("Ran a tool.")
    activity_widget = panel.last_message_widget()
    panel.append_error_message("It failed.")
    error_widget = panel.last_message_widget()

    assert activity_widget is not None and error_widget is not None
    # Qt returns an empty QPalette override when a widget never called setPalette()/
    # setStyleSheet() for a color -- both rows share the same (absent) override.
    assert activity_widget.styleSheet() == ""
    assert error_widget.styleSheet() == ""


# -- Criterion 1: tool-call results render through the SAME ResultCard/registry path ------------


def test_append_tool_result_constructs_the_real_result_card_class(
    qapp: QApplication,
) -> None:
    """Milestone 22's ResultCard, not a chat-specific reimplementation.

    A plain dict is exactly the shape src.ai.tool_registry's own handlers return (see
    result_renderer_registry's GenericResultRenderer docstring naming this as its "defensive
    path for a JSON-friendly dict"); ResultCard.display() resolves it via
    result_renderer_registry.get_renderer internally -- this test asserts the widget appended is
    a real ResultCard instance, i.e. the chat panel's own code constructs that class and calls
    its real display() method rather than building parallel section widgets itself.
    """
    panel = ChatPanel()
    panel.append_tool_result(
        {"row_count": 10, "column_count": 3}, ExpertiseLevel.BEGINNER
    )

    widget = panel.last_message_widget()
    assert isinstance(widget, ResultCard)
    # ResultCard.display() actually ran and rendered something -- not an empty shell.
    assert widget.section_widgets


def test_append_tool_result_is_reachable_from_the_conversation_flow(
    qapp: QApplication,
) -> None:
    """Several rows can be appended in the natural chat order: user, tool result, assistant."""
    panel = ChatPanel()
    panel.append_user_message("Run a t-test on revenue by region.")
    panel.append_tool_result(
        {"statistic": 2.1, "p_value": 0.04}, ExpertiseLevel.ANALYST
    )
    panel.append_assistant_message("The difference is statistically significant.")

    assert panel._message_list.count() == 3
    assert isinstance(
        panel._message_list.itemWidget(panel._message_list.item(1)), ResultCard
    )


# -- Criterion 5 (widget half): "Clear Chat" button exists and clears the transcript ------------


def test_clear_button_exists_and_is_described(qapp: QApplication) -> None:
    panel = ChatPanel()
    assert panel.clear_button.text() == "Clear Chat"
    assert panel.clear_button.accessibleName() == "Clear chat"


def test_clear_transcript_empties_the_visible_message_list(qapp: QApplication) -> None:
    panel = ChatPanel()
    panel.append_user_message("Hello")
    panel.append_assistant_message("Hi there")
    assert panel._message_list.count() == 2

    panel.clear_transcript()

    assert panel._message_list.count() == 0


# -- Criterion 4 (widget half): a live expertise-level selector exists --------------------------


def test_expertise_combo_offers_every_expertise_level(qapp: QApplication) -> None:
    panel = ChatPanel()
    values = {
        panel.expertise_combo.itemData(i) for i in range(panel.expertise_combo.count())
    }
    assert values == {level.value for level in ExpertiseLevel}


# -- Criterion 6 (widget half): states "no provider configured" plainly and stays usable --------


def test_provider_status_states_no_provider_configured_plainly_at_construction(
    qapp: QApplication,
) -> None:
    panel = ChatPanel()
    text = panel.provider_status_text()
    assert "No AI provider configured" in text
    assert "Settings" in text


def test_input_remains_usable_with_no_provider_configured(qapp: QApplication) -> None:
    """The pre-milestone-21 panel started with set_ready(False) and only ever re-enabled input
    after a *successful* turn -- with no provider configured, that meant input was permanently
    disabled and a user could never even attempt to send a message to discover why. Input is now
    usable from construction, so an attempt to send is what actually surfaces the explanation
    (see AssistantController._get_or_build_assistant_service)."""
    panel = ChatPanel()
    assert panel._input_field.isEnabled()
    assert panel.send_button.isEnabled()

    panel.set_input_text("Hello?")
    assert panel.current_input_text() == "Hello?"
