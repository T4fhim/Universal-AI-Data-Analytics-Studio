# File: src/ui/controllers/assistant_controller.py
"""Owns lazy AssistantService construction and the chat-panel send/result/error flow.

Moved out of ``main_window.py`` in milestone 19 -- see
:mod:`src.ui.controllers`'s own docstring for why this package exists.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from src.ai.assistant_service import AssistantService, AssistantTurnResult
from src.core.exceptions import ServiceError
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
        expertise_level = self._settings_service.get(
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
