# File: src/ui/controllers/assistant_controller.py
"""Owns lazy AssistantService construction and the chat-panel send/result/error flow.

Moved out of ``main_window.py`` in milestone 19 -- see
:mod:`src.ui.controllers`'s own docstring for why this package exists.

Milestone 21 adds two things on top of that: a live path for
:meth:`~src.ai.assistant_service.AssistantService.set_expertise_level`
(previously only reachable by writing ``ai.expertise_level`` to config
and restarting -- the setter existed and was tested since milestone 8,
but nothing in the UI ever called it on an already-running service),
and routing :attr:`~src.ai.assistant_service.AssistantTurnResult.
new_tool_results` through :meth:`~src.ui.widgets.chat_panel.ChatPanel.
append_tool_result`.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from src.ai.assistant_service import AssistantService, AssistantTurnResult
from src.core.exceptions import ServiceError
from src.core.expertise_level import ExpertiseLevel
from src.core.logger import get_logger
from src.services.settings_service import SettingsService
from src.services.workspace_service import WorkspaceService
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.worker_runner import WorkerRunner

_logger = get_logger(__name__)


class AssistantController:
    """Handles the AI chat panel: lazy service construction, sending, and turn results.

    Args:
        parent: The window dialogs should be parented to.
        settings_service: Where provider profiles/rotation/expertise
            settings are read from to construct :class:`AssistantService`
            on first use.
        workspace_service: Checked for an active dataset before a turn is
            sent, and refreshed if a tool call created new datasets.
        dock_manager: Owns the chat panel widget itself and the console.
        status_bar: For busy feedback while a turn is in flight.
        worker_runner: Runs the (potentially slow, network-bound)
            assistant turn off the UI thread.
    """

    def __init__(
        self,
        parent: QWidget,
        settings_service: SettingsService,
        workspace_service: WorkspaceService,
        dock_manager: DockManager,
        status_bar: ApplicationStatusBar,
        worker_runner: WorkerRunner,
    ) -> None:
        self._parent = parent
        self._settings_service = settings_service
        self._workspace_service = workspace_service
        self._dock_manager = dock_manager
        self._status_bar = status_bar
        self._worker_runner = worker_runner
        # Constructed lazily on first chat message, not eagerly here --
        # building it eagerly would mean every window construction
        # (including ones where the user never opens the AI panel) pays
        # the cost of resolving provider profiles and would show a "no
        # provider configured" error before the user has done anything.
        # See _get_or_build_assistant_service.
        self._assistant_service: AssistantService | None = None
        # Milestone 21: a user-chosen expertise level that overrides
        # SettingsService's "ai.expertise_level" for this session, set
        # via the chat panel's live selector before or after
        # AssistantService exists. Applied immediately if the service
        # is already running (AssistantService.set_expertise_level);
        # otherwise applied at construction time in
        # _get_or_build_assistant_service, so a change made before the
        # first message is sent is not silently lost. None means "use
        # whatever SettingsService currently has," the pre-milestone-21
        # behavior.
        self._expertise_level_override: str | None = None

    def _get_or_build_assistant_service(self) -> AssistantService | None:
        """Return the running :class:`AssistantService`, constructing it from config on first use.

        Returns ``None`` (after showing an explanatory dialog) if no
        provider is configured or construction otherwise fails --
        callers must check for this rather than assuming a non-``None``
        return, since "not configured yet" is a normal, expected state
        for a freshly installed application, not an error to raise past
        the UI layer.
        """
        if self._assistant_service is not None:
            return self._assistant_service

        providers = self._settings_service.get("ai", "providers", default=[])
        rotation_enabled = self._settings_service.get(
            "ai", "rotation_enabled", default=False
        )
        # A pending live override (set before this service existed) wins over
        # SettingsService -- see _expertise_level_override's own docstring.
        expertise_level = self._expertise_level_override or self._settings_service.get(
            "ai", "expertise_level", default="beginner"
        )

        try:
            service = AssistantService.from_provider_profiles(
                providers, rotation_enabled, self._workspace_service, expertise_level
            )
        except ServiceError as exc:
            QMessageBox.information(
                self._parent, "AI Assistant Not Configured", str(exc)
            )
            return None

        self._assistant_service = service
        self._dock_manager.chat_panel.set_provider_label(
            f"Provider: {service.active_provider_name}"
        )
        _logger.info(
            "AssistantService constructed (provider: %s).", service.active_provider_name
        )
        return service

    def set_expertise_level(self, level: str) -> None:
        """Update the expertise level live -- no restart required.

        Args:
            level: An :class:`~src.core.expertise_level.ExpertiseLevel`
                value, e.g. ``"engineer"``.

        Applies immediately to the running
        :class:`~src.ai.assistant_service.AssistantService` (via its
        own :meth:`~src.ai.assistant_service.AssistantService.
        set_expertise_level`, in effect from the *next* turn onward --
        see that method's own docstring) if one has been constructed
        already; always records the choice as this session's override
        so a service constructed *after* this call also picks it up
        (see :attr:`_expertise_level_override`'s own docstring), rather
        than requiring the user to change it again once a service
        happens to exist.
        """
        self._expertise_level_override = level
        if self._assistant_service is not None:
            self._assistant_service.set_expertise_level(level)
        _logger.info(
            "Expertise level set to %r (%s).",
            level,
            "applied live" if self._assistant_service is not None else "pending",
        )

    def on_expertise_level_changed(self, index: int) -> None:
        """Slot for the chat panel's expertise combo's ``currentIndexChanged`` signal."""
        level = self._dock_manager.chat_panel.expertise_combo.itemData(index)
        if not level:
            return  # defensive: an empty/uninitialized combo should not clear a real choice
        self.set_expertise_level(level)

    def clear_chat(self) -> None:
        """ "Clear Chat": reset the running conversation and the visible transcript.

        Calls the previously-orphaned
        :meth:`~src.ai.assistant_service.AssistantService.
        reset_conversation` -- orphaned because nothing in the UI ever
        called it before this milestone. A session with no service
        constructed yet (:attr:`_assistant_service` is ``None``) has no
        conversation to reset; the visible transcript is cleared
        either way, so pressing "Clear Chat" before ever sending a
        message is still a well-defined no-op rather than an error.
        """
        if self._assistant_service is not None:
            self._assistant_service.reset_conversation()
        self._dock_manager.chat_panel.clear_transcript()
        self._dock_manager.append_console_message("AI assistant conversation cleared.")

    def send_chat_message(self) -> None:
        chat_panel = self._dock_manager.chat_panel
        text = chat_panel.current_input_text()
        if not text:
            return

        if self._workspace_service.get_active_dataset() is None:
            QMessageBox.information(
                self._parent,
                "No Active Dataset",
                "Open or select a dataset before using the AI assistant.",
            )
            return

        service = self._get_or_build_assistant_service()
        if service is None:
            return  # _get_or_build_assistant_service already explained why

        chat_panel.append_user_message(text)
        chat_panel.clear_input()
        chat_panel.set_ready(False)
        self._status_bar.show_busy("Waiting for AI assistant…")

        self._worker_runner.run(
            service.send_message,
            text,
            on_result=self._on_assistant_turn_result,
            on_error=self._on_assistant_turn_error,
            on_finished=self._on_assistant_turn_finished,
        )

    def _on_assistant_turn_result(self, result: AssistantTurnResult) -> None:
        chat_panel = self._dock_manager.chat_panel
        chat_panel.append_assistant_message(result.reply_text)
        self._dock_manager.append_console_message("AI assistant turn completed.")

        if result.new_datasets:
            chat_panel.append_tool_activity(
                f"Created {len(result.new_datasets)} new dataset(s): "
                f"{', '.join(d.name for d in result.new_datasets)}."
            )
            self._dock_manager.append_console_message(
                f"AI tool created dataset(s): "
                f"{', '.join(d.name for d in result.new_datasets)}."
            )
            self._dock_manager.refresh_dataset_list(
                self._workspace_service.list_datasets()
            )

        for visualization in result.new_visualizations:
            chat_panel.append_tool_activity(
                f"Created visualization: {visualization.name}."
            )
            self._dock_manager.append_console_message(
                f"AI tool created visualization: {visualization.name}."
            )
            self._dock_manager.display_chart(
                visualization.figure, name=visualization.name
            )

        if result.new_tool_results:
            # Milestone 21: render each tool call's structured result through the same
            # ResultCard/result_renderer_registry path a stage page uses -- see
            # ChatPanel.append_tool_result's own docstring. self._assistant_service is
            # guaranteed non-None here (send_chat_message already used it to get this
            # result), so .expertise_level reads the level the conversation is actually
            # running at right now, not a stale default.
            level = (
                self._assistant_service.expertise_level
                if self._assistant_service is not None
                else ExpertiseLevel.BEGINNER
            )
            for tool_result in result.new_tool_results:
                chat_panel.append_tool_result(tool_result, level)

        if self._assistant_service is not None:
            # Reflects any rotation that happened mid-turn (milestone 7)
            # -- the label may now name a different provider profile than
            # it did before this turn started.
            chat_panel.set_provider_label(
                f"Provider: {self._assistant_service.active_provider_name}"
            )

    def _on_assistant_turn_error(self, exc: Exception, traceback_text: str) -> None:
        self._dock_manager.chat_panel.append_error_message(str(exc))
        self._dock_manager.append_console_message(f"⚠ AI assistant turn failed: {exc}")
        _logger.warning("Assistant turn failed: %s\n%s", exc, traceback_text)

    def _on_assistant_turn_finished(self) -> None:
        self._status_bar.hide_busy()
        self._dock_manager.chat_panel.set_ready(True)
