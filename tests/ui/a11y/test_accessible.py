# File: tests/ui/a11y/test_accessible.py
"""Tests for the describe/label_for/set_tab_order/announce helpers.

These are the functions every later milestone is expected to call at widget
construction time -- see src/ui/a11y/__init__.py for why they are free
functions rather than a mixin.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton

from src.ui.a11y.accessible import (
    HELP_ANCHOR_PROPERTY,
    announce,
    describe,
    label_for,
    set_tab_order,
)


def test_describe_sets_name_description_tooltip_statustip(qapp: QApplication) -> None:
    button = QPushButton()
    describe(
        button,
        name="Open Dataset",
        description="Load a data file into the workspace",
        status_tip="Opens a file picker",
        help_anchor="data/open-dataset",
    )
    assert button.accessibleName() == "Open Dataset"
    assert button.accessibleDescription() == "Load a data file into the workspace"
    assert button.toolTip() == "Load a data file into the workspace"
    assert button.statusTip() == "Opens a file picker"
    assert button.property(HELP_ANCHOR_PROPERTY) == "data/open-dataset"


def test_describe_promotes_no_focus_to_strong_focus_by_default(
    qapp: QApplication,
) -> None:
    button = QPushButton()
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    describe(button, name="Run")
    assert button.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_describe_focusable_false_leaves_no_focus_alone(qapp: QApplication) -> None:
    label = QLabel()
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    describe(label, name="Section heading", focusable=False)
    assert label.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_describe_does_not_downgrade_an_existing_non_default_focus_policy(
    qapp: QApplication,
) -> None:
    """A widget that deliberately chose ClickFocus keeps it."""
    button = QPushButton()
    button.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    describe(button, name="Something")
    assert button.focusPolicy() == Qt.FocusPolicy.ClickFocus


def test_describe_tooltip_override_wins_over_description(qapp: QApplication) -> None:
    button = QPushButton()
    describe(button, name="X", description="long form", tooltip="short form")
    assert button.toolTip() == "short form"
    assert button.accessibleDescription() == "long form"


@pytest.mark.parametrize("bad_name", ["", "   ", "\t\n"])
def test_describe_rejects_empty_or_whitespace_name(
    qapp: QApplication, bad_name: str
) -> None:
    button = QPushButton()
    with pytest.raises(ValueError, match="non-empty accessible name"):
        describe(button, name=bad_name)


def test_label_for_sets_buddy_and_mirrors_stripped_text(qapp: QApplication) -> None:
    field = QLineEdit()
    label = QLabel("&Host:")
    label_for(field, label)
    assert label.buddy() is field
    assert field.accessibleName() == "Host"


def test_label_for_accepts_an_explicit_name_override(qapp: QApplication) -> None:
    field = QLineEdit()
    label = QLabel("Port:")
    label_for(field, label, name="Database Port Number")
    assert field.accessibleName() == "Database Port Number"


def test_set_tab_order_chains_pairwise(qapp: QApplication) -> None:
    """Cannot assert the actual Qt tab chain offscreen without a shown
    window, so this asserts the call does not raise across 0, 1, and N
    widgets -- the degenerate cases that matter for a caller building the
    list conditionally.
    """
    set_tab_order()  # zero widgets
    set_tab_order(QLineEdit())  # one widget
    set_tab_order(QLineEdit(), QLineEdit(), QLineEdit())  # three


def test_announce_sets_description_and_does_not_raise_with_empty_message(
    qapp: QApplication,
) -> None:
    button = QPushButton()
    announce(button, "Analysis complete")
    assert button.accessibleDescription() == "Analysis complete"
    announce(button, "")  # must not raise
