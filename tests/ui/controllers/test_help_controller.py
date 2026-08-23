# File: tests/ui/controllers/test_help_controller.py
"""HelpController's fallback chain: focus anchor -> current stage page -> "index"."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMainWindow, QPushButton

from src.ui.a11y.accessible import describe
from src.ui.controllers.help_controller import HelpController


def _pump_events(app: QApplication) -> None:
    """``processEvents()``, tolerating one specific, pre-existing, unrelated flake.

    A prior test elsewhere in the full ``tests/ui/`` run can leave a coalesced
    ``UiStateBus._emit_state_changed`` deferred call queued against a ``MainWindow``/
    ``UiStateBus`` pair that has since been closed and garbage-collected on the C++ side --
    confirmed pre-existing (not introduced by this milestone) by reverting every tracked-file
    change this milestone made and reproducing the identical crash with only this milestone's
    new, untracked test files present. The very next ``processEvents()`` call *by any test*
    then raises ``RuntimeError: Signal source has been deleted`` when that stale deferred call
    finally fires -- nothing to do with focus/anchor resolution, which is what this module
    actually tests. Only this exact, identified error is swallowed; anything else propagates
    normally. Flagged for the architect in this milestone's own "As built" note rather than
    fixed here -- ``src/ui/ui_state_bus.py`` is a foundational module this milestone's scope
    never otherwise touches.
    """
    try:
        app.processEvents()
    except RuntimeError as exc:
        if "Signal source has been deleted" not in str(exc):
            raise


class _FakeStagePage:
    help_anchor = "pipeline.understand"


class _FakeWorkbenchNoCurrentPage:
    def current_page(self):
        return None


class _FakeWorkbenchWithCurrentPage:
    def current_page(self):
        return _FakeStagePage()


def test_falls_back_to_index_when_nothing_has_focus_and_no_stage_page_is_current(
    qapp,
) -> None:
    window = QMainWindow()
    controller = HelpController(window, _FakeWorkbenchNoCurrentPage())
    controller.show_help_for_focus()
    assert controller._dialog is not None
    assert controller._dialog._current_anchor == "index"


def test_falls_back_to_the_current_stage_page_when_focus_has_no_anchor(qapp) -> None:
    window = QMainWindow()
    button = QPushButton("no anchor", window)
    window.show()
    button.setFocus()
    _pump_events(qapp)
    assert (
        qapp.focusWidget() is button
    )  # otherwise this test would pass for the wrong reason
    controller = HelpController(window, _FakeWorkbenchWithCurrentPage())

    controller.show_help_for_focus()

    assert controller._dialog._current_anchor == "pipeline.understand"
    window.close()


def test_a_focused_widgets_own_anchor_wins_over_the_current_stage_page(qapp) -> None:
    window = QMainWindow()
    button = QPushButton("has anchor", window)
    describe(button, name="Has anchor", help_anchor="settings")
    window.show()
    button.setFocus()
    _pump_events(qapp)
    assert (
        qapp.focusWidget() is button
    )  # otherwise this test would pass for the wrong reason
    controller = HelpController(window, _FakeWorkbenchWithCurrentPage())

    controller.show_help_for_focus()

    assert controller._dialog._current_anchor == "settings"
    window.close()


def test_show_manual_reuses_the_same_dialog_instance(qapp) -> None:
    window = QMainWindow()
    controller = HelpController(window, _FakeWorkbenchNoCurrentPage())

    controller.show_manual("index")
    first_dialog = controller._dialog
    controller.show_manual("settings")

    assert controller._dialog is first_dialog
    assert controller._dialog._current_anchor == "settings"


def test_the_shortcut_is_bound_to_help_contents_and_opens_the_manual(qapp) -> None:
    """Proves F1 is actually wired end to end -- not merely that show_help_for_focus works in
    isolation. Activates the real QShortcut this controller owns (the same signal a real F1
    keypress fires), rather than calling show_help_for_focus directly, so a future refactor
    that accidentally drops the shortcut connection itself would be caught here."""
    from PySide6.QtGui import QKeySequence

    window = QMainWindow()
    controller = HelpController(window, _FakeWorkbenchNoCurrentPage())

    assert controller._shortcut.key() == QKeySequence(
        QKeySequence.StandardKey.HelpContents
    )
    controller._shortcut.activated.emit()

    assert controller._dialog is not None
    assert controller._dialog._current_anchor == "index"
