# File: src/ui/widgets/chat_panel.py
"""The AI chat panel's widget content (milestone 10, overhauled milestone 21).

Pure UI: message list, input box, a status label showing which
provider profile is currently active (transparency into milestone 7's
rotation) and whether a turn is in flight. Wiring this to a real
:class:`~src.ai.assistant_service.AssistantService` — constructing the
service from configured provider profiles, running ``send_message``
on a worker thread (milestone 6), refreshing the dataset/chart docks
when a turn produces new ones — is :mod:`src.ui.main_window`'s job,
the same "structure here, behavior wired by the caller" split every
other dock's widget in this package already follows.

Milestone 21 closes three defects the original audit named in this file:

1. ``setSelectionMode(NoSelection)`` made every message unreachable by
   keyboard, unreadable by a screen reader as anything but list noise,
   and uncopyable. Fixed by keeping the list's default (single-item)
   selection mode and rendering each message as a real, focusable
   ``QLabel`` (via ``setItemWidget``, not ``QListWidgetItem.setText``)
   with selectable text and a :func:`~src.ui.a11y.accessible.describe`
   call giving it a real accessible name/description — the same
   mechanism every other widget added since milestone 15 uses.
2. Tool-activity/error rows signaled state with an icon glyph *plus* a
   gray/red foreground color; the color was the redundant half (WCAG
   1.4.1), not the only half — but nothing gave a screen-reader user a
   *name* distinguishing "this is a status row" from an ordinary
   message. ``describe()`` now stamps each with an accessible name
   ("Tool activity" / "Error") independent of both the glyph and the
   color, so removing the color entirely (also done here, since a
   ``QLabel``'s foreground is theme-driven and re-coloring it row by
   row fought that instead of using it) loses no information.
3. Tool-call results (a JSON-friendly ``dict`` — see
   :mod:`src.ai.tool_registry`'s own docstring) now render through
   :class:`~src.ui.results.result_card.ResultCard`, the exact class
   :mod:`~src.ui.workbench.pages.analyze_page` uses, via
   :meth:`append_tool_result` — not a second, chat-specific renderer.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.expertise_level import ExpertiseLevel
from src.core.logger import get_logger
from src.ui.a11y.accessible import describe
from src.ui.results.result_card import ResultCard

_logger = get_logger(__name__)

# Prepended to a tool-activity/error row's visible text -- kept even though describe() also
# gives each row a distinct accessible name, since a sighted user scanning the list relies on
# the glyph+text, not on hovering for a tooltip. Removing the *color* (the actual WCAG 1.4.1
# defect -- color was redundant with, not the only carrier of, this information) loses nothing
# because the glyph and the row's accessible name both already convey the same distinction.
_TOOL_ACTIVITY_GLYPH = "⚙"
_ERROR_GLYPH = "⚠"

_NO_PROVIDER_TEXT = "No AI provider configured — add one in Settings."


class ChatPanel(QWidget):
    """The AI Assistant dock's content: conversation history + message input."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()
        self._provider_label = QLabel(_NO_PROVIDER_TEXT, self)
        self._provider_label.setObjectName("chatProviderLabel")
        self._provider_label.setWordWrap(True)
        describe(
            self._provider_label,
            name="AI provider status",
            description=(
                "States which AI provider is currently active, or that "
                "none is configured."
            ),
            focusable=False,  # a status readout, not a control to tab to
        )
        header_row.addWidget(self._provider_label, 1)

        # Milestone 21: a live expertise-level selector, wired by
        # AssistantController.on_expertise_level_changed to
        # AssistantService.set_expertise_level -- previously that
        # setter was only ever reachable via config + an app restart
        # (SettingsService.set() only takes effect the *next* time
        # AssistantController lazily constructs a fresh
        # AssistantService; see that controller's own docstring).
        self.expertise_combo = QComboBox(self)
        self.expertise_combo.setObjectName("chatExpertiseCombo")
        for level in ExpertiseLevel:
            self.expertise_combo.addItem(
                level.value.replace("_", " ").title(), level.value
            )
        describe(
            self.expertise_combo,
            name="Explanation detail level",
            description=(
                "How much statistical background to assume when the "
                "assistant explains a result -- changes take effect "
                "immediately, mid-conversation."
            ),
        )
        header_row.addWidget(self.expertise_combo)

        self.clear_button = QPushButton("Clear Chat", self)
        self.clear_button.setObjectName("chatClearButton")
        describe(
            self.clear_button,
            name="Clear chat",
            description=(
                "Clears the visible conversation and resets the "
                "assistant's conversation history, starting fresh."
            ),
        )
        header_row.addWidget(self.clear_button)
        layout.addLayout(header_row)

        # A QListWidget rather than a rich QTextEdit conversation view:
        # each entry is one turn (user message, assistant reply, a
        # tool-activity note, or -- milestone 21 -- a tool-call result
        # rendered as a real ResultCard), and a list gives per-item
        # widgets (see _add_row_widget below) with far less code than
        # implementing chat-bubble rendering in a text document.
        #
        # The default SelectionMode (SingleSelection) is deliberately
        # left alone here -- an earlier version of this file called
        # setSelectionMode(NoSelection), which made every message
        # unselectable, uncopyable, and unreachable by keyboard
        # (milestone 21's fix; see this module's own docstring).
        self._message_list = QListWidget(self)
        self._message_list.setObjectName("chatMessageList")
        self._message_list.setWordWrap(True)
        describe(
            self._message_list,
            name="Conversation history",
            description="The messages exchanged with the AI assistant so far.",
        )
        layout.addWidget(self._message_list, 1)

        input_row = QHBoxLayout()
        self._input_field = QLineEdit(self)
        self._input_field.setPlaceholderText("Ask about the active dataset…")
        self._input_field.returnPressed.connect(self._on_return_pressed)
        describe(
            self._input_field,
            name="Message to the AI assistant",
            description="Type a question about the active dataset, then press Send.",
        )
        input_row.addWidget(self._input_field)

        self.send_button = QPushButton("Send", self)
        describe(
            self.send_button,
            name="Send message",
            description="Sends the typed message to the AI assistant.",
        )
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

        # Enabled from construction, unlike the pre-milestone-21 version
        # (which started disabled and was only ever re-enabled after a
        # *successful* turn finished -- see AssistantController.
        # _on_assistant_turn_finished). With no provider configured
        # that meant the input was permanently unusable, and the "no
        # provider" explanation was reachable only by reading the
        # static label above, not by attempting to send. Leaving input
        # enabled lets that attempt happen and produce the explanatory
        # dialog AssistantController._get_or_build_assistant_service
        # already shows -- turning "no API key configured" from a
        # silent dead control into a real, user-triggered explanation.
        self.set_ready(True)
        _logger.debug("Chat panel constructed.")

    def _on_return_pressed(self) -> None:
        if self.send_button.isEnabled():
            self.send_button.click()

    def current_input_text(self) -> str:
        return self._input_field.text().strip()

    def set_input_text(self, text: str) -> None:
        """Set the message input's text -- used by tests to script a send without a real key event."""
        self._input_field.setText(text)

    def clear_input(self) -> None:
        self._input_field.clear()

    def provider_status_text(self) -> str:
        """The provider status label's current text -- what a "no API key configured" test reads."""
        return self._provider_label.text()

    def append_user_message(self, text: str) -> None:
        self._append_text_row(f"You: {text}", name="You said", description=text)

    def append_assistant_message(self, text: str) -> None:
        self._append_text_row(
            f"Assistant: {text}", name="Assistant replied", description=text
        )

    def append_tool_activity(self, text: str) -> None:
        """Show a transparency note about a tool call the assistant just ran.

        Ties into "Explain Everything" from the defining-features
        list: the user sees *that* a tool ran (and what it produced),
        not just the assistant's final summarized reply — matches
        :class:`~src.ai.assistant_service.AssistantTurnResult`
        exposing ``new_datasets``/``new_visualizations`` rather than
        only ``reply_text``.
        """
        self._append_text_row(
            f"{_TOOL_ACTIVITY_GLYPH} {text}", name="Tool activity", description=text
        )

    def append_error_message(self, text: str) -> None:
        self._append_text_row(f"{_ERROR_GLYPH} {text}", name="Error", description=text)

    def append_tool_result(self, result: Any, level: ExpertiseLevel) -> None:
        """Render one tool call's structured result via the same widget a stage page shows.

        Args:
            result: Any tool-call result object --
                :class:`~src.ai.assistant_service.AssistantTurnResult.
                new_tool_results` is where this comes from, one call
                per entry. Constructs a real
                :class:`~src.ui.results.result_card.ResultCard` and
                calls its real :meth:`~src.ui.results.result_card.
                ResultCard.display`, which itself resolves ``result``
                via :func:`~src.ui.results.result_renderer_registry.
                get_renderer` — the identical path
                :mod:`~src.ui.workbench.pages.analyze_page` uses. This
                method deliberately does not branch on ``type(result)``
                or format anything itself; doing so would be exactly
                the second, chat-specific rendering path this
                milestone's acceptance criteria rule out.
            level: Which :class:`~src.core.expertise_level.
                ExpertiseLevel` to render for -- the caller
                (:class:`~src.ui.controllers.assistant_controller.
                AssistantController`) passes the conversation's live
                :attr:`~src.ai.assistant_service.AssistantService.
                expertise_level`.
        """
        card = ResultCard(self)
        card.display(result, level)
        self._add_row_widget(card)

    def clear_transcript(self) -> None:
        """Remove every visible message row -- the "Clear Chat" button's UI half.

        Pure UI: clearing the *conversation state*
        (:meth:`~src.ai.assistant_service.AssistantService.
        reset_conversation`) is
        :class:`~src.ui.controllers.assistant_controller.
        AssistantController`'s job, matching this file's own "structure
        here, behavior wired by the caller" split — this method only
        empties what is on screen.
        """
        self._message_list.clear()

    def last_message_widget(self) -> QWidget | None:
        """The most recently appended row's embedded widget, or ``None`` if the list is empty.

        Exists for tests: every message row is a real widget embedded
        via ``setItemWidget`` (see :meth:`_add_row_widget`), not
        ``QListWidgetItem`` text, so a test asserting on accessible
        name, focus policy, or ``isinstance(..., ResultCard)`` needs a
        way to reach it without groping through ``QListWidget``
        internals itself.
        """
        count = self._message_list.count()
        if count == 0:
            return None
        return self._message_list.itemWidget(self._message_list.item(count - 1))

    def _append_text_row(
        self, display_text: str, *, name: str, description: str
    ) -> None:
        label = QLabel(display_text, self)
        label.setWordWrap(True)
        # TextSelectableByMouse + TextSelectableByKeyboard is what makes a message copyable
        # (Ctrl+C / right-click Copy) -- a plain QLabel's default interaction flags select
        # nothing at all, which is half of the "copyable" defect this milestone fixes.
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        describe(label, name=name, description=description)
        self._add_row_widget(label)

    def _add_row_widget(self, widget: QWidget) -> None:
        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        self._message_list.addItem(item)
        self._message_list.setItemWidget(item, widget)
        self._message_list.scrollToBottom()

    def set_provider_label(self, text: str) -> None:
        self._provider_label.setText(text)

    def set_ready(self, ready: bool) -> None:
        """Enable/disable input — used both for "no provider configured" and "turn in flight".

        Args:
            ready: ``True`` if the user should be able to type and send
                a message right now.
        """
        self._input_field.setEnabled(ready)
        self.send_button.setEnabled(ready)
