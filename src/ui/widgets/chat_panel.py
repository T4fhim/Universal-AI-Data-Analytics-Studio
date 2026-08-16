# File: src/ui/widgets/chat_panel.py
"""The AI chat panel's widget content (milestone 10).

Pure UI: message list, input box, a status label showing which
provider profile is currently active (transparency into milestone 7's
rotation) and whether a turn is in flight. Wiring this to a real
:class:`~src.ai.assistant_service.AssistantService` — constructing the
service from configured provider profiles, running ``send_message``
on a worker thread (milestone 6), refreshing the dataset/chart docks
when a turn produces new ones — is :mod:`src.ui.main_window`'s job,
the same "structure here, behavior wired by the caller" split every
other dock's widget in this package already follows.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.core.logger import get_logger

_logger = get_logger(__name__)


class ChatPanel(QWidget):
    """The AI Assistant dock's content: conversation history + message input."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)

        self._provider_label = QLabel(
            "No AI provider configured — add one in Settings."
        )
        self._provider_label.setObjectName("chatProviderLabel")
        self._provider_label.setWordWrap(True)
        layout.addWidget(self._provider_label)

        # A QListWidget rather than a rich QTextEdit conversation view:
        # each entry is one turn (user message, assistant reply, or a
        # tool-activity note), and a list gives per-item styling
        # (see _append below) with far less code than implementing
        # chat-bubble rendering in a text document — appropriate for a
        # first working version of a panel that previously did not
        # exist at all.
        self._message_list = QListWidget(self)
        self._message_list.setWordWrap(True)
        self._message_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._message_list, 1)

        input_row = QHBoxLayout()
        self._input_field = QLineEdit(self)
        self._input_field.setPlaceholderText("Ask about the active dataset…")
        self._input_field.returnPressed.connect(self._on_return_pressed)
        input_row.addWidget(self._input_field)

        self.send_button = QPushButton("Send", self)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

        self.set_ready(False)  # no provider configured yet at construction time
        _logger.debug("Chat panel constructed.")

    def _on_return_pressed(self) -> None:
        if self.send_button.isEnabled():
            self.send_button.click()

    def current_input_text(self) -> str:
        return self._input_field.text().strip()

    def clear_input(self) -> None:
        self._input_field.clear()

    def append_user_message(self, text: str) -> None:
        self._append(f"You: {text}")

    def append_assistant_message(self, text: str) -> None:
        self._append(f"Assistant: {text}")

    def append_tool_activity(self, text: str) -> None:
        """Show a transparency note about a tool call the assistant just ran.

        Ties into "Explain Everything" from the defining-features
        list: the user sees *that* a tool ran (and what it produced),
        not just the assistant's final summarized reply — matches
        :class:`~src.ai.assistant_service.AssistantTurnResult`
        exposing ``new_datasets``/``new_visualizations`` rather than
        only ``reply_text``.
        """
        item = QListWidgetItem(f"⚙ {text}")
        item.setForeground(Qt.GlobalColor.gray)
        self._message_list.addItem(item)
        self._message_list.scrollToBottom()

    def append_error_message(self, text: str) -> None:
        item = QListWidgetItem(f"⚠ {text}")
        item.setForeground(Qt.GlobalColor.red)
        self._message_list.addItem(item)
        self._message_list.scrollToBottom()

    def _append(self, text: str) -> None:
        self._message_list.addItem(QListWidgetItem(text))
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
