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

    main_window._on_new_project()
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
