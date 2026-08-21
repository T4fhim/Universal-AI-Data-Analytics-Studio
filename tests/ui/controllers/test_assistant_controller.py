# File: tests/ui/controllers/test_assistant_controller.py
"""Tests for AssistantController, covering milestone 21's acceptance criteria.

Uses real WorkspaceService/SettingsService/DockManager/WorkerRunner (not fakes) -- the same
"duck-typed fakes only for Qt-adjacent collaborators, real services for the actual business
logic under test" split ``tests/ui/controllers/test_project_controller.py``/
``test_pipeline_controller.py`` established -- plus ``tests.ai.conftest``'s ``FakeLLMProvider``
seam, since a real ``AssistantService`` conversation is what these criteria are actually about
(set_expertise_level, reset_conversation, tool-result routing), not a rebuilt double of it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication, QMainWindow

from src.ai.llm_provider import LLMTurn, PendingToolCall
from src.core.config import AppConfig, load_config
from src.services.settings_service import SettingsService
from src.services.workspace_service import Dataset, WorkspaceService
from src.ui.controllers.assistant_controller import AssistantController
from src.ui.dock_manager import DockManager
from src.ui.results.result_card import ResultCard
from src.ui.status_bar import ApplicationStatusBar
from src.ui.worker_runner import WorkerRunner
from tests.ai.conftest import make_provider

_FAKE_PROVIDER_PROFILE = {
    "name": "test-anthropic",
    "provider_type": "anthropic",
    "api_key_env_var": "UADS_TEST_FAKE_KEY",
    "model": "test-model",
}


def _make_dataset() -> Dataset:
    frame = pd.DataFrame(
        {
            "revenue": [100.0, 200.0, 150.0, 400.0, 90.0, 300.0],
            "region": ["east", "east", "east", "west", "west", "west"],
        }
    )
    return Dataset(name="sales", dataframe=frame, source_format="csv")


def _make_settings_service(tmp_path, *, with_provider: bool) -> SettingsService:
    config_path = tmp_path / "config.yaml"
    config = AppConfig.from_dict(load_config(config_path))
    service = SettingsService(config, config_path)
    if with_provider:
        service.set("ai", "providers", value=[_FAKE_PROVIDER_PROFILE])
    return service


def _make_controller(
    settings_service: SettingsService, workspace_service: WorkspaceService
) -> tuple[AssistantController, QMainWindow]:
    window = QMainWindow()
    dock_manager = DockManager(window)
    status_bar = ApplicationStatusBar(window)
    worker_runner = WorkerRunner(window)
    controller = AssistantController(
        window,
        settings_service,
        workspace_service,
        dock_manager,
        status_bar,
        worker_runner,
    )
    return controller, window


def _synchronous_run(
    fn: Callable[..., Any],
    *args: Any,
    on_result: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception, str], None] | None = None,
    on_finished: Callable[[], None] | None = None,
    on_progress: Callable[[int, str], None] | None = None,
    report_progress: bool = False,
    **kwargs: Any,
) -> None:
    """A same-thread stand-in for ``WorkerRunner.run`` matching its own callback contract.

    The real ``WorkerRunner.run`` launches ``fn`` on ``QThreadPool.globalInstance()`` -- a
    single, session-scoped pool shared with every other UI test in this suite (see
    ``tests/ui/conftest.py``'s session-scoped ``qapp`` fixture). Waiting on a specific worker's
    ``finished`` signal was observed to occasionally time out (even at 15s) only when running the
    *entire* ``tests/`` suite, never in isolation or alongside just ``tests/ui/`` -- a real
    property of a shared, session-lifetime thread pool under combined load from ~900 other
    tests, not a fact about ``AssistantController``'s own logic. ``WorkerRunner``'s actual
    threading behavior already has dedicated coverage in ``tests/ui/test_worker_runner.py``; this
    fake keeps these tests exercising the real ``AssistantService.send_message()`` call and the
    real ``AssistantController`` callback methods it drives, deterministically, without also
    depending on the shared pool scheduling a thread promptly.
    """
    try:
        result = fn(*args, **kwargs)
    except (
        Exception
    ) as exc:  # noqa: BLE001 -- mirrors BaseWorker's own catch-all boundary
        if on_error is not None:
            on_error(exc, "")
    else:
        if on_result is not None:
            on_result(result)
    finally:
        if on_finished is not None:
            on_finished()


def _send_and_wait(controller: AssistantController, text: str) -> None:
    chat_panel = controller._dock_manager.chat_panel
    chat_panel.set_input_text(text)
    controller._worker_runner.run = _synchronous_run  # type: ignore[method-assign,assignment]
    controller.send_chat_message()


# -- Criterion 4: set_expertise_level is reachable live, no restart required --------------------


def test_set_expertise_level_applies_live_to_an_already_running_service(
    qapp: QApplication, block_modals, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    workspace = WorkspaceService()
    dataset = _make_dataset()
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)
    settings_service = _make_settings_service(tmp_path, with_provider=True)

    turns = [LLMTurn(text="Understood.", tool_calls=[])]
    make_provider(monkeypatch, turns)

    controller, _window = _make_controller(settings_service, workspace)
    _send_and_wait(controller, "Hello")  # constructs the real AssistantService

    assert controller._assistant_service is not None
    assert controller._assistant_service.expertise_level.value == "beginner"

    controller.set_expertise_level("engineer")

    assert controller._assistant_service.expertise_level.value == "engineer"


def test_set_expertise_level_before_construction_is_applied_when_the_service_is_built(
    qapp: QApplication, block_modals, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A change made before the first message still takes effect -- not silently dropped."""
    workspace = WorkspaceService()
    dataset = _make_dataset()
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)
    settings_service = _make_settings_service(tmp_path, with_provider=True)

    turns = [LLMTurn(text="Understood.", tool_calls=[])]
    make_provider(monkeypatch, turns)

    controller, _window = _make_controller(settings_service, workspace)
    assert controller._assistant_service is None

    controller.set_expertise_level("researcher")
    _send_and_wait(controller, "Hello")

    assert controller._assistant_service is not None
    assert controller._assistant_service.expertise_level.value == "researcher"


def test_on_expertise_level_changed_reads_the_combo_and_delegates(
    qapp: QApplication, block_modals, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The chat panel's own combo -- the actual UI control -- reaches the same live path."""
    workspace = WorkspaceService()
    settings_service = _make_settings_service(tmp_path, with_provider=True)
    controller, _window = _make_controller(settings_service, workspace)
    combo = controller._dock_manager.chat_panel.expertise_combo
    engineer_index = combo.findData("engineer")
    assert engineer_index >= 0

    controller.on_expertise_level_changed(engineer_index)

    assert controller._expertise_level_override == "engineer"


# -- Criterion 5: "Clear Chat" calls the real reset_conversation() ------------------------------


def test_clear_chat_calls_reset_conversation_on_a_running_service(
    qapp: QApplication, block_modals, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    workspace = WorkspaceService()
    dataset = _make_dataset()
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)
    settings_service = _make_settings_service(tmp_path, with_provider=True)

    turns = [LLMTurn(text="Understood.", tool_calls=[])]
    make_provider(monkeypatch, turns)

    controller, _window = _make_controller(settings_service, workspace)
    _send_and_wait(controller, "Hello")
    service = controller._assistant_service
    assert service is not None
    assert service._history != []  # a real, non-empty conversation exists

    controller.clear_chat()

    assert (
        service._history == []
    )  # reset_conversation() actually ran, not a UI-only clear
    assert controller._dock_manager.chat_panel._message_list.count() == 0


def test_clear_chat_button_click_drives_the_same_path(
    qapp: QApplication, block_modals, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Simulates main_window.py's own clicked.connect wiring, not just calling clear_chat()
    directly -- proves the button really is wired to the real controller method."""
    workspace = WorkspaceService()
    dataset = _make_dataset()
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)
    settings_service = _make_settings_service(tmp_path, with_provider=True)

    turns = [LLMTurn(text="Understood.", tool_calls=[])]
    make_provider(monkeypatch, turns)

    controller, _window = _make_controller(settings_service, workspace)
    chat_panel = controller._dock_manager.chat_panel
    chat_panel.clear_button.clicked.connect(controller.clear_chat)
    _send_and_wait(controller, "Hello")
    assert controller._assistant_service is not None
    assert controller._assistant_service._history != []

    chat_panel.clear_button.click()

    assert controller._assistant_service._history == []
    assert chat_panel._message_list.count() == 0


def test_clear_chat_with_no_service_constructed_yet_is_a_well_defined_no_op(
    qapp: QApplication, block_modals, tmp_path
) -> None:
    workspace = WorkspaceService()
    settings_service = _make_settings_service(tmp_path, with_provider=False)
    controller, _window = _make_controller(settings_service, workspace)
    chat_panel = controller._dock_manager.chat_panel
    chat_panel.append_user_message("Hi")

    controller.clear_chat()  # must not raise despite _assistant_service being None

    assert chat_panel._message_list.count() == 0


# -- Criterion 1: tool-call results reach the chat panel via ResultCard -------------------------


def test_a_tool_call_result_reaches_the_chat_panel_as_a_real_result_card(
    qapp: QApplication, block_modals, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    workspace = WorkspaceService()
    dataset = _make_dataset()
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)
    settings_service = _make_settings_service(tmp_path, with_provider=True)

    turns = [
        LLMTurn(
            text="",
            tool_calls=[
                PendingToolCall(
                    call_id="1",
                    name="independent_t_test",
                    arguments={
                        "value_column": "revenue",
                        "group_column": "region",
                        "group_a": "east",
                        "group_b": "west",
                    },
                )
            ],
        ),
        LLMTurn(text="Ran the t-test.", tool_calls=[]),
    ]
    make_provider(monkeypatch, turns)

    controller, _window = _make_controller(settings_service, workspace)
    _send_and_wait(controller, "Compare revenue between regions.")

    chat_panel = controller._dock_manager.chat_panel
    row_widgets = [
        chat_panel._message_list.itemWidget(chat_panel._message_list.item(i))
        for i in range(chat_panel._message_list.count())
    ]
    result_card_widgets = [w for w in row_widgets if isinstance(w, ResultCard)]
    assert len(result_card_widgets) == 1
    assert result_card_widgets[
        0
    ].section_widgets  # a real render happened, not an empty card


# -- Criterion 6: no API key configured states this plainly, rest of app stays usable -----------


def test_sending_with_no_provider_configured_shows_a_plain_explanation(
    qapp: QApplication, block_modals, tmp_path
) -> None:
    workspace = WorkspaceService()
    dataset = _make_dataset()
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)
    settings_service = _make_settings_service(tmp_path, with_provider=False)
    controller, _window = _make_controller(settings_service, workspace)
    chat_panel = controller._dock_manager.chat_panel
    chat_panel.set_input_text("Hello?")

    controller.send_chat_message()

    assert len(block_modals) == 1
    assert block_modals[0].kind == "information"
    assert "No AI provider is configured" in block_modals[0].text
    assert controller._assistant_service is None


def test_rest_of_the_app_stays_fully_usable_with_no_api_key_configured(
    qapp: QApplication, block_modals, tmp_path
) -> None:
    """An unrelated part of the app -- running a real statistical test from the Analyze stage
    page, exactly like tests/ui/workbench/test_analyze_page.py's own milestone-22 acceptance
    test -- works fully in the same no-API-key session as the chat panel above. Constructing
    AnalyzePage/running independent_t_test never imports src.ai, so this is unaffected by the
    chat panel's own "not configured" state by construction, not merely by accident."""
    from src.core.expertise_level import ExpertiseLevel
    from src.ui.workbench.pages.analyze_page import AnalyzePage

    workspace = WorkspaceService()
    dataset = _make_dataset()
    workspace.add_dataset(dataset)
    workspace.set_active_dataset(dataset.dataset_id)
    settings_service = _make_settings_service(tmp_path, with_provider=False)
    controller, _window = _make_controller(settings_service, workspace)
    chat_panel = controller._dock_manager.chat_panel
    assert "No AI provider configured" in chat_panel.provider_status_text()

    page = AnalyzePage()
    page.set_dataset(dataset)
    page.run_analysis(
        dataset,
        "independent_t_test",
        {
            "value_column": "revenue",
            "group_column": "region",
            "group_a": "east",
            "group_b": "west",
        },
        ExpertiseLevel.BEGINNER,
    )

    assert page.result_card.section_widgets
    assert not any(call.kind == "critical" for call in block_modals)
