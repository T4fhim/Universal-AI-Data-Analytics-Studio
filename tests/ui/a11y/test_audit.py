# File: tests/ui/a11y/test_audit.py
"""Proves the M28 acceptance gate: a fully populated ``MainWindow`` audits clean.

This is the test every milestone from M16 onward left as an unchecked
acceptance box, per that milestone's own plan section, because
``audit_widget_tree`` did not exist yet -- see e.g. M16's own "the audit
*tool* itself is M28 scope and doesn't exist yet" scope note. Running against
a real, fully constructed :class:`~src.ui.main_window.MainWindow` (not a bare
test double) is what makes this test the actual closure of those boxes,
rather than a second, narrower promise.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from PySide6.QtWidgets import QApplication, QDialog

from src.core.bootstrap import bootstrap
from src.services.workspace_service import Dataset
from src.ui.a11y.audit import ALL_DIALOG_CLASSES, Severity, audit_widget_tree
from src.ui.main_window import MainWindow
from src.ui.theme.tokens import TOKENS_BY_NAME
from src.ui.theme_manager import ThemeManager


@pytest.fixture()
def themed_main_window(
    qapp: QApplication,
    config_path: Path,
    log_dir: Path,
    reset_logging_state,
) -> MainWindow:
    """A real ``MainWindow`` with a real theme attached, dataset loaded.

    Loads a dataset (not just the welcome page) so the workbench's stage
    pages -- which only exist once a dataset is active, see
    :meth:`~src.ui.main_window.MainWindow._refresh_workbench` -- are actually
    constructed and walkable, matching what "fully populated" means for this
    acceptance criterion.
    """
    context = bootstrap(config_path=config_path, log_dir=log_dir)
    window = MainWindow(context)
    theme_manager = ThemeManager(qapp)
    theme_manager.apply_theme("dark")
    window.attach_theme_manager(theme_manager)

    dataset = Dataset(
        name="audit-fixture",
        dataframe=pd.DataFrame({"category": ["a", "b", "a"], "value": [1.0, 2.0, 3.0]}),
        source_format="csv",
    )
    window._dataset_controller.load_dataset(dataset)

    window.setProperty("_test_theme_manager", theme_manager)
    yield window
    window.close()


def test_audit_widget_tree_finds_zero_errors_against_a_populated_main_window(
    themed_main_window: MainWindow,
) -> None:
    theme_manager: ThemeManager = themed_main_window.property("_test_theme_manager")
    findings = audit_widget_tree(
        themed_main_window, tokens=theme_manager.current_tokens()
    )
    errors = [f for f in findings if f.severity is Severity.ERROR]
    assert errors == [], "\n".join(str(f) for f in errors)


@pytest.mark.parametrize("theme_name", list(TOKENS_BY_NAME))
def test_audit_widget_tree_contrast_check_passes_every_theme(
    themed_main_window: MainWindow, theme_name: str
) -> None:
    """The contrast rule specifically, against every theme including high_contrast.

    Separate from the whole-window test above (which only exercises whatever
    theme that fixture happened to apply) so a contrast regression in a theme
    nobody is actively viewing still fails here.
    """
    findings = audit_widget_tree(themed_main_window, tokens=TOKENS_BY_NAME[theme_name])
    contrast_errors = [f for f in findings if f.rule_id == "contrast"]
    assert contrast_errors == [], "\n".join(str(f) for f in contrast_errors)


def test_audit_widget_tree_skips_contrast_when_no_tokens_given(
    themed_main_window: MainWindow,
) -> None:
    findings = audit_widget_tree(themed_main_window)
    assert not any(f.rule_id == "contrast" for f in findings)


# -- ALL_DIALOG_CLASSES: discovered, not hand-maintained -----------------------------------------


def test_all_dialog_classes_is_discovered_and_nonempty() -> None:
    assert len(ALL_DIALOG_CLASSES) > 0
    for dialog_class in ALL_DIALOG_CLASSES:
        assert issubclass(dialog_class, QDialog)


def test_all_dialog_classes_includes_known_dialogs() -> None:
    """A spot-check that the introspection mechanism actually reaches every
    dialog-carrying subpackage (top-level ``src/ui/`` and ``src/ui/dialogs/``),
    not just one of them.
    """
    names = {cls.__qualname__ for cls in ALL_DIALOG_CLASSES}
    assert "SettingsDialog" in names
    assert "AboutDialog" in names
    assert "CommandPalette" in names  # top-level src/ui/, not src/ui/dialogs/


def test_all_dialog_classes_has_no_duplicates() -> None:
    assert len(ALL_DIALOG_CLASSES) == len(set(ALL_DIALOG_CLASSES))
