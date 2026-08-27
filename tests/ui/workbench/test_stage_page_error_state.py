# File: tests/ui/workbench/test_stage_page_error_state.py
"""Tests for StagePage's milestone-27 show_error/clear_error -- the in-page ErrorState every
StagePage subclass gets for free (see stage_page.py's own docstring on why a stage-page failure
is persistent page state rather than a one-shot QMessageBox.critical interruption).

Uses UnderstandPage as a concrete stand-in -- StagePage itself is abstract (a subclass must set
``stage``), and the show_error/clear_error behavior under test lives entirely in the base class,
so any concrete subclass exercises it identically (the same "one concrete stand-in is enough"
reasoning ``test_pages.py`` already uses per-page for its own page-specific assertions).
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.ui.workbench.pages.understand_page import UnderstandPage


def test_error_state_starts_hidden(qapp: QApplication) -> None:
    # isHidden(), not isVisible() -- these pages are never QMainWindow.show()n in a headless
    # test, so isVisible() (which also depends on the whole ancestor chain being shown) would
    # read False either way; isHidden() reflects only this widget's own explicit
    # setVisible()/hide() state, matching test_dock_manager_workbench.py's own
    # dock_chart.isHidden() precedent for the same reason.
    page = UnderstandPage()
    assert page._error_state.isHidden() is True


def test_show_error_makes_the_error_state_visible_with_the_given_text(
    qapp: QApplication,
) -> None:
    page = UnderstandPage()

    page.show_error("Exploration Failed", "Column 'x' not found.")

    assert page._error_state.isHidden() is False
    assert page._error_state._heading_label.text() == "Exploration Failed"
    assert page._error_state._message_label.text() == "Column 'x' not found."


def test_clear_error_hides_the_error_state(qapp: QApplication) -> None:
    page = UnderstandPage()
    page.show_error("Exploration Failed", "Column 'x' not found.")

    page.clear_error()

    assert page._error_state.isHidden() is True
