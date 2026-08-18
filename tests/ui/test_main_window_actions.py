# File: tests/ui/test_main_window_actions.py
"""End-to-end smoke coverage for MainWindow's milestone-17 action wiring.

Constructs a real MainWindow (isolated config/log dirs, per
tests/conftest.py) rather than mocking ActionBinder/ActionContext away --
this is the test that would have caught the pre-milestone-17 dead-action
defect (Undo/Redo, Open Recent) directly: assert_all_bound() raising here
means MainWindow.__init__ itself would have failed to construct.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.core.bootstrap import bootstrap
from src.ui.actions.action_context import ActionContext
from src.ui.main_window import MainWindow


@pytest.fixture()
def main_window(
    qapp: QApplication,
    config_path: Path,
    log_dir: Path,
    reset_logging_state,
) -> MainWindow:
    context = bootstrap(config_path=config_path, log_dir=log_dir)
    window = MainWindow(context)
    yield window
    window.close()


def test_main_window_constructs_without_raising(main_window: MainWindow) -> None:
    """If any registered ActionSpec had no bound handler, __init__ itself
    would have raised ServiceError via assert_all_bound() -- reaching this
    line at all is the assertion.
    """
    assert main_window is not None


def test_save_project_action_starts_disabled_with_no_project_open(
    main_window: MainWindow,
) -> None:
    action = main_window._binder.action_for("project.save")
    assert action.isEnabled() is False


def test_new_project_enables_save_action(
    main_window: MainWindow, qapp: QApplication
) -> None:
    from tests.ui.qt_helpers import process_events

    main_window._project_controller.new_project()
    process_events()  # let UiStateBus's coalesced singleShot(0, ...) fire

    action = main_window._binder.action_for("project.save")
    assert action.isEnabled() is True


def test_dashboard_action_disabled_below_two_visualizations(
    main_window: MainWindow,
) -> None:
    action = main_window._binder.action_for("analysis.dashboard")
    assert action.isEnabled() is False


def test_context_capture_against_real_services_does_not_raise(
    main_window: MainWindow,
) -> None:
    """A structural check that ActionContext.capture() (used by
    _on_ui_state_changed) works against a freshly constructed window's
    real services, not just the fakes test_action_context.py uses.
    """
    context = ActionContext.capture(
        project_service=main_window._project_service,
        workspace_service=main_window._workspace_service,
        settings_service=main_window._settings_service,
    )
    assert context.has_project is False
    assert context.has_active_dataset is False


def test_close_event_closes_every_live_database_connection(
    main_window: MainWindow,
) -> None:
    """Milestone 19: before this, closeEvent never called
    DatabaseConnectionService.close_all_connections() at all -- a
    connection opened via Connect to Database stayed open until the
    process exited rather than being released when the window closed.
    """
    calls: list[bool] = []
    main_window._database_service.close_all_connections = lambda: calls.append(True)

    main_window.close()

    assert calls == [True]


# -- Milestone 20: Workbench as the central widget --------------------------------------------


def test_workbench_is_the_central_widget(main_window: MainWindow) -> None:
    """Acceptance criterion 1: Workbench, not WelcomeWidget, is the central widget."""
    from src.ui.workbench.workbench import Workbench

    assert isinstance(main_window.centralWidget(), Workbench)
    assert main_window.centralWidget() is main_window._workbench


def test_opening_a_dataset_transitions_the_workbench_off_the_welcome_page(
    main_window: MainWindow, qapp: QApplication
) -> None:
    """Acceptance criterion 1, end to end through a real dataset load."""
    import pandas as pd

    from src.services.workspace_service import Dataset
    from tests.ui.qt_helpers import process_events

    dataset = Dataset(
        name="test", dataframe=pd.DataFrame({"a": [1, 2, 3]}), source_format="csv"
    )

    main_window._dataset_controller.load_dataset(dataset)
    process_events()

    assert (
        main_window._workbench.stack.currentWidget()
        is not main_window._workbench.welcome_page
    )


def test_opening_a_dataset_shows_upload_complete_and_understand_proposed_on_the_rail(
    main_window: MainWindow, qapp: QApplication
) -> None:
    """Acceptance criterion 2, end to end through real services."""
    import pandas as pd

    from src.services.analysis_orchestrator_service import PipelineStage
    from src.services.workspace_service import Dataset
    from tests.ui.qt_helpers import process_events

    dataset = Dataset(
        name="test", dataframe=pd.DataFrame({"a": [1, 2, 3]}), source_format="csv"
    )

    main_window._dataset_controller.load_dataset(dataset)
    process_events()

    rail = main_window._workbench.stage_rail
    assert rail.status_for(PipelineStage.UPLOAD) == "complete"
    assert rail.status_for(PipelineStage.UNDERSTAND) == "proposed"

    understand_page = main_window._workbench.page_for(PipelineStage.UNDERSTAND)
    assert understand_page._guidance_label.text()  # the real StageProposal.rationale


def test_clicking_run_on_understand_produces_a_real_log_entry_end_to_end(
    main_window: MainWindow, qapp: QApplication
) -> None:
    """Acceptance criterion 3, driven through the actual page's Run button."""
    import pandas as pd

    from src.services.analysis_orchestrator_service import PipelineStage
    from src.services.workspace_service import Dataset
    from tests.ui.qt_helpers import process_events, wait_for_signal

    dataset = Dataset(
        name="test", dataframe=pd.DataFrame({"a": [1, 2, 3]}), source_format="csv"
    )
    main_window._dataset_controller.load_dataset(dataset)
    process_events()

    # Capture the real BaseWorker run_understand_stage starts, so this test
    # can block on its own `finished` signal (a real Qt wait) rather than a
    # fixed process_events() tick count, which was measured to be flaky
    # here. Deliberately calls QPushButton.click() directly -- NOT
    # tests.ui.qt_helpers.click(), whose own process_events() call can let
    # a fast worker finish (and deliver its `finished` signal) before this
    # test's wait_for_signal below has a chance to connect, which would
    # then wait for a signal that has already fired and time out.
    original_run = main_window._pipeline_controller._worker_runner.run
    started_workers: list = []

    def _capturing_run(*args, **kwargs):
        worker = original_run(*args, **kwargs)
        started_workers.append(worker)
        return worker

    main_window._pipeline_controller._worker_runner.run = _capturing_run

    understand_page = main_window._workbench.page_for(PipelineStage.UNDERSTAND)
    understand_page.run_button.click()
    wait_for_signal(started_workers[0].signals.finished)
    process_events()  # let the queued on_result callback itself run

    log = main_window._orchestrator_service.get_log(dataset.dataset_id)
    assert len(log.entries) == 1
    assert log.entries[0].tool_name == "profile_dataset"
    assert (
        "1,204" not in understand_page._result_label.text()
    )  # sanity: real data, not a stub
    assert "3" in understand_page._result_label.text()  # 3 rows, profiled for real
