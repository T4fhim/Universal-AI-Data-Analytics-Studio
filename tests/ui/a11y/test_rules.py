# File: tests/ui/a11y/test_rules.py
"""Unit tests for each individual rule in :mod:`src.ui.a11y.rules`.

``tests/ui/a11y/test_audit.py`` proves the *whole* rule set is clean against
a real application; this module proves each rule actually detects the defect
it claims to, in isolation, against small hand-built widget trees -- so a
rule that silently stopped checking anything (e.g. an accidentally-inverted
condition) would still fail a test even though nothing in the real app
happens to trigger it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDockWidget,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.a11y.accessible import describe
from src.ui.a11y.rules import (
    Severity,
    _check_button_names,
    _check_dialog_not_a_trap,
    _check_dock_titles,
    _check_duplicate_shortcuts,
    _check_field_names,
    _check_focus_reachable,
    _check_illustration_descriptions,
    contrast_findings,
)
from src.ui.theme.tokens import DARK_TOKENS


def _tree(*widgets: QWidget) -> tuple[QWidget, list[QWidget]]:
    root = QWidget()
    layout = QVBoxLayout(root)
    for widget in widgets:
        layout.addWidget(widget)
    all_widgets = [root, *root.findChildren(QWidget)]
    return root, all_widgets


def test_button_names_flags_an_unnamed_icon_only_button(qapp: QApplication) -> None:
    button = QPushButton()  # no text, no describe()
    root, all_widgets = _tree(button)
    findings = _check_button_names(root, all_widgets)
    assert len(findings) == 1
    assert findings[0].severity is Severity.ERROR
    assert findings[0].rule_id == "interactive-name"


def test_button_names_accepts_visible_text(qapp: QApplication) -> None:
    button = QPushButton("Run")
    root, all_widgets = _tree(button)
    assert _check_button_names(root, all_widgets) == []


def test_button_names_accepts_an_explicit_accessible_name(qapp: QApplication) -> None:
    button = QPushButton()
    describe(button, name="Run analysis")
    root, all_widgets = _tree(button)
    assert _check_button_names(root, all_widgets) == []


def test_field_names_flags_an_unlabeled_line_edit(qapp: QApplication) -> None:
    field = QLineEdit()
    root, all_widgets = _tree(field)
    findings = _check_field_names(root, all_widgets)
    assert len(findings) == 1
    assert findings[0].rule_id == "input-buddy"


def test_field_names_accepts_a_buddy_label(qapp: QApplication) -> None:
    field = QLineEdit()
    label = QLabel("Name:")
    label.setBuddy(field)
    root, all_widgets = _tree(label, field)
    assert _check_field_names(root, all_widgets) == []


def test_field_names_accepts_an_explicit_accessible_name(qapp: QApplication) -> None:
    combo = QComboBox()
    describe(combo, name="Chart type")
    root, all_widgets = _tree(combo)
    assert _check_field_names(root, all_widgets) == []


def test_field_names_placeholder_text_alone_does_not_count(qapp: QApplication) -> None:
    """A QLineEdit's placeholder is only visible while empty, not a substitute
    for a real accessible name -- see src/ui/command_palette.py's own M28 fix
    for the real defect this exact case represents."""
    field = QLineEdit()
    field.setPlaceholderText("Type to search…")
    root, all_widgets = _tree(field)
    assert len(_check_field_names(root, all_widgets)) == 1


def test_focus_reachable_flags_no_focus_on_an_interactive_widget(
    qapp: QApplication,
) -> None:
    button = QPushButton("Run")
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    root, all_widgets = _tree(button)
    findings = _check_focus_reachable(root, all_widgets)
    assert len(findings) == 1
    assert findings[0].rule_id == "focus-reachable"


def test_focus_reachable_accepts_strong_focus(qapp: QApplication) -> None:
    button = QPushButton("Run")
    assert (
        button.focusPolicy() != Qt.FocusPolicy.NoFocus
    )  # QPushButton's own Qt default
    root, all_widgets = _tree(button)
    assert _check_focus_reachable(root, all_widgets) == []


def test_dialog_not_a_trap_flags_a_dialog_with_no_focusable_content(
    qapp: QApplication,
) -> None:
    dialog = QDialog()
    label = QLabel("Just some prose", dialog)
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    layout = QVBoxLayout(dialog)
    layout.addWidget(label)
    root = QWidget()
    inner_layout = QVBoxLayout(root)
    inner_layout.addWidget(dialog)
    all_widgets = [root, *root.findChildren(QWidget)]
    findings = _check_dialog_not_a_trap(root, all_widgets)
    assert len(findings) == 1
    assert findings[0].rule_id == "dialog-focus-trap"


def test_dialog_not_a_trap_accepts_a_dialog_with_a_focusable_button(
    qapp: QApplication,
) -> None:
    dialog = QDialog()
    button = QPushButton("OK", dialog)
    layout = QVBoxLayout(dialog)
    layout.addWidget(button)
    root = QWidget()
    inner_layout = QVBoxLayout(root)
    inner_layout.addWidget(dialog)
    all_widgets = [root, *root.findChildren(QWidget)]
    assert _check_dialog_not_a_trap(root, all_widgets) == []


def test_dialog_not_a_trap_ignores_an_empty_dialog(qapp: QApplication) -> None:
    dialog = QDialog()
    root = QWidget()
    layout = QVBoxLayout(root)
    layout.addWidget(dialog)
    all_widgets = [root, *root.findChildren(QWidget)]
    assert _check_dialog_not_a_trap(root, all_widgets) == []


def test_duplicate_shortcuts_flags_two_window_scoped_actions_sharing_a_key(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    first = QAction("First", window)
    first.setShortcut("Ctrl+Z")
    second = QAction("Second", window)
    second.setShortcut("Ctrl+Z")
    window.addAction(first)
    window.addAction(second)
    all_widgets = [window, *window.findChildren(QWidget)]
    findings = _check_duplicate_shortcuts(window, all_widgets)
    assert len(findings) == 1
    assert findings[0].rule_id == "duplicate-shortcut"
    window.close()


def test_duplicate_shortcuts_ignores_widget_scoped_conflicts(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    first = QAction("First", window)
    first.setShortcut("Ctrl+Z")
    first.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
    second = QAction("Second", window)
    second.setShortcut("Ctrl+Z")
    second.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
    window.addAction(first)
    window.addAction(second)
    all_widgets = [window, *window.findChildren(QWidget)]
    assert _check_duplicate_shortcuts(window, all_widgets) == []
    window.close()


def test_dock_titles_flags_an_untitled_dock(qapp: QApplication) -> None:
    window = QMainWindow()
    dock = QDockWidget(window)  # no setWindowTitle
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    all_widgets = [window, *window.findChildren(QWidget)]
    findings = _check_dock_titles(window, all_widgets)
    assert len(findings) == 1
    assert findings[0].rule_id == "dock-title"
    window.close()


def test_dock_titles_accepts_a_titled_dock(qapp: QApplication) -> None:
    window = QMainWindow()
    dock = QDockWidget("Dataset Explorer", window)
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    all_widgets = [window, *window.findChildren(QWidget)]
    assert _check_dock_titles(window, all_widgets) == []
    window.close()


def test_illustration_descriptions_flags_a_pixmap_only_label(
    qapp: QApplication,
) -> None:
    from src.ui.widgets.empty_state import render_illustration

    label = QLabel()
    label.setPixmap(render_illustration("empty-search", "#ffffff"))
    root, all_widgets = _tree(label)
    findings = _check_illustration_descriptions(root, all_widgets)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING


def test_illustration_descriptions_accepts_a_described_label(
    qapp: QApplication,
) -> None:
    from src.ui.widgets.empty_state import render_illustration

    label = QLabel()
    label.setPixmap(render_illustration("empty-search", "#ffffff"))
    describe(label, name="No datasets", description="Illustration of an empty search")
    root, all_widgets = _tree(label)
    assert _check_illustration_descriptions(root, all_widgets) == []


def test_illustration_descriptions_ignores_text_only_labels(qapp: QApplication) -> None:
    label = QLabel("Plain text, no pixmap")
    root, all_widgets = _tree(label)
    assert _check_illustration_descriptions(root, all_widgets) == []


# -- contrast_findings: reuses contrast.py math against a deliberately-bad token set --------------


def test_contrast_findings_is_empty_for_the_real_dark_tokens() -> None:
    assert contrast_findings(DARK_TOKENS) == []


def test_contrast_findings_flags_a_deliberately_low_contrast_pairing() -> None:
    from dataclasses import replace

    bad_tokens = replace(DARK_TOKENS, text_primary=DARK_TOKENS.surface_0)
    findings = contrast_findings(bad_tokens)
    assert any(f.rule_id == "contrast" for f in findings)
    assert all(
        f.severity is Severity.ERROR for f in findings if f.rule_id == "contrast"
    )
