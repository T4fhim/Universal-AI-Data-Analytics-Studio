# File: tests/ui/test_status_bar.py
"""Tests for ApplicationStatusBar, focused on milestone 28's reduced-motion busy indicator.

No test file existed for this widget before milestone 28 -- its busy/progress
methods had only been exercised incidentally through worker-signal wiring
tests elsewhere. Reduced motion is the first genuinely widget-owned
behavior this class has (everything else is thin wrapping over
``QStatusBar``), so it is what gets dedicated coverage here.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMainWindow

from src.ui.status_bar import ApplicationStatusBar


def test_show_busy_defaults_to_indeterminate(qapp: QApplication) -> None:
    window = QMainWindow()
    bar = ApplicationStatusBar(window)
    window.setStatusBar(bar)  # matches src/ui/main_window.py's real wiring
    window.show()
    bar.show_busy()
    assert bar._busy_indicator.maximum() == 0
    assert bar._busy_indicator.isVisible() is True
    window.close()


def test_show_busy_is_static_when_reduced_motion_enabled(qapp: QApplication) -> None:
    window = QMainWindow()
    bar = ApplicationStatusBar(window)
    bar.set_reduced_motion(True)
    bar.show_busy()
    assert bar._busy_indicator.maximum() == 1
    assert bar._busy_indicator.value() == 1
    window.close()


def test_set_reduced_motion_updates_an_already_busy_indicator(
    qapp: QApplication,
) -> None:
    """Takes effect immediately, even before the window has ever been shown --
    this is exactly why the busy state is tracked with an explicit flag
    rather than read back via QProgressBar.isVisible() (which would be
    False here, offscreen, with no window.show() call at all)."""
    window = QMainWindow()
    bar = ApplicationStatusBar(window)
    bar.show_busy()
    assert bar._busy_indicator.maximum() == 0

    bar.set_reduced_motion(True)

    assert bar._busy_indicator.maximum() == 1
    window.close()


def test_set_reduced_motion_back_to_false_restores_indeterminate(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    bar = ApplicationStatusBar(window)
    bar.set_reduced_motion(True)
    bar.show_busy()
    assert bar._busy_indicator.maximum() == 1

    bar.set_reduced_motion(False)

    assert bar._busy_indicator.maximum() == 0
    window.close()


def test_set_reduced_motion_does_not_disturb_a_real_percentage(
    qapp: QApplication,
) -> None:
    """A determinate show_progress() report is genuine information -- toggling
    reduced motion must not silently overwrite it."""
    window = QMainWindow()
    bar = ApplicationStatusBar(window)
    bar.show_busy()
    bar.show_progress(42, "Almost there")

    bar.set_reduced_motion(True)

    assert bar._busy_indicator.maximum() == 100
    assert bar._busy_indicator.value() == 42
    window.close()


def test_set_reduced_motion_to_the_same_value_is_a_noop(qapp: QApplication) -> None:
    window = QMainWindow()
    bar = ApplicationStatusBar(window)
    bar.set_reduced_motion(False)  # already the default
    bar.show_busy()
    assert bar._busy_indicator.maximum() == 0
    window.close()


def test_hide_busy_hides_the_indicator_regardless_of_reduced_motion(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    bar = ApplicationStatusBar(window)
    bar.set_reduced_motion(True)
    bar.show_busy()
    bar.hide_busy()
    assert bar._busy_indicator.isVisible() is False
    window.close()
