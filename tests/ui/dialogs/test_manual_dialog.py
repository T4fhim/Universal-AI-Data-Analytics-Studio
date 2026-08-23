# File: tests/ui/dialogs/test_manual_dialog.py
"""ManualDialog against the real docs/manual/ tree -- the actual content it will ever show."""

from __future__ import annotations

from PySide6.QtWidgets import QMainWindow

from src.ui.dialogs.manual_dialog import ManualDialog


def test_show_anchor_sets_title_and_renders_html(qapp) -> None:
    window = QMainWindow()
    dialog = ManualDialog(window)
    dialog.show_anchor("index")
    assert "Manual:" in dialog.windowTitle()
    # QTextBrowser re-serializes its own QTextDocument (styled spans, not literal <h1> tags) --
    # asserting on the rendered *text* content is what actually proves the real page's prose
    # made it into the widget, independent of Qt's own internal HTML round-trip format.
    assert "Manual" in dialog._browser.toPlainText()


def test_show_anchor_falls_back_to_index_for_an_unknown_anchor(qapp) -> None:
    window = QMainWindow()
    dialog = ManualDialog(window)
    dialog.show_anchor("this-anchor-does-not-exist")
    assert dialog._current_anchor == "index"


def test_is_not_modal(qapp) -> None:
    window = QMainWindow()
    dialog = ManualDialog(window)
    assert dialog.isModal() is False


def test_link_click_navigates_to_a_cross_referenced_page(qapp) -> None:
    from PySide6.QtCore import QUrl

    window = QMainWindow()
    dialog = ManualDialog(window)
    dialog.show_anchor("data/open-dataset")  # links to ../readers/csv.md, among others
    dialog._on_link_clicked(QUrl("../readers/csv.md"))
    assert dialog._current_anchor == "readers.csv"


def test_link_click_with_no_matching_page_is_a_silent_no_op(qapp) -> None:
    from PySide6.QtCore import QUrl

    window = QMainWindow()
    dialog = ManualDialog(window)
    dialog.show_anchor("index")
    dialog._on_link_clicked(QUrl("../nonexistent/page.md"))
    assert dialog._current_anchor == "index"  # unchanged, no crash
