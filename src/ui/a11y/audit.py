# File: src/ui/a11y/audit.py
"""Walks a real widget tree and reports accessibility defects, so "the app is
accessible" is a claim this module can actually check rather than one every
milestone since M15 has had to leave as an unchecked acceptance box.

:mod:`src.ui.a11y.accessible` gives call sites a single, easy way to *do the
right thing* (``describe()``). It cannot, by itself, prove that every call
site actually used it -- a widget nobody remembered to describe fails
silently, discoverable only by someone tabbing through the whole application
with a screen reader running. :func:`audit_widget_tree` is the automated
check that closes that gap: it walks a live widget tree from any root
(typically a fully constructed :class:`~src.ui.main_window.MainWindow`) and
returns every :class:`A11yFinding` the rules in :mod:`src.ui.a11y.rules`
detect, so a regression is a test failure instead of a screen-reader session
away from being noticed.

**What this does not replace.** Automated checks catch roughly a third of
real accessibility defects industry-wide (the plan this module implements
cites that figure directly) -- this is a floor, not a substitute for a human
screen-reader pass. See ``docs/M28_MANUAL_VERIFICATION.md`` for the manual
NVDA walkthrough this module's existence makes it possible to schedule, but
does not itself perform.

**Contrast is delegated, not reimplemented.** :func:`~src.ui.a11y.rules.
contrast_findings` reuses :mod:`src.ui.theme.contrast`'s WCAG math and
:data:`~src.ui.a11y.contrast_manifest.CONTRAST_REQUIREMENTS` -- the same
pairing list ``tests/ui/theme/test_contrast.py`` already asserts against
every theme. Reinventing that math here would risk the two silently
disagreeing about what "passes" means.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

from PySide6.QtWidgets import QDialog, QWidget

from src.core.logger import get_logger
from src.ui.a11y import rules
from src.ui.a11y.rules import A11yFinding, Severity
from src.ui.theme.tokens import ThemeTokens

# The path to src/ui/, derived from this file's own location rather than by
# `import src.ui` -- this package is one of the "leaf" foundation layers
# tests/ui/test_import_layering.py holds to "imports nothing else from
# src.ui" (a real, enforced architectural rule, not a style preference), and
# `import src.ui` would violate it even though the only thing actually
# needed is the directory pkgutil.walk_packages walks, not any name the
# src.ui package itself defines.
_SRC_UI_DIR = Path(__file__).resolve().parent.parent

_logger = get_logger(__name__)

# Re-exported so a caller only needs to import this module for the whole
# public surface (``audit_widget_tree``, ``A11yFinding``, ``Severity``,
# ``ALL_DIALOG_CLASSES``) without also reaching into ``src.ui.a11y.rules`` --
# the vocabulary types live there (see that module's own docstring for why)
# purely to avoid the circular import that would result from defining them
# here instead: ``rules.py``'s check functions all return ``A11yFinding``s
# and therefore must be able to import the dataclass without importing this
# module back.
__all__ = [
    "ALL_DIALOG_CLASSES",
    "A11yFinding",
    "Severity",
    "audit_widget_tree",
    "describe_widget",
]


def describe_widget(widget: QWidget, root: QWidget | None = None) -> str:
    """Build a human-readable ancestor-chain description of ``widget``.

    Args:
        widget: The widget a finding is about.
        root: Stop walking ancestors once this widget is reached (inclusive).
            ``None`` walks to the top-level window, which is what a finding
            report normally wants -- ``root`` exists mainly so
            :func:`audit_widget_tree` can stop exactly at the widget it was
            called with even when that widget is itself nested inside a
            bigger, unrelated live application window.

    Each link in the chain is ``ClassName`` alone, or ``ClassName#objectName``
    when an ``objectName`` was actually set -- most widgets in this codebase
    do not set one, and a bare class name repeated at every level is still
    more locatable than nothing.
    """
    chain: list[str] = []
    current: QWidget | None = widget
    while current is not None:
        object_name = current.objectName()
        label = (
            f"{type(current).__name__}#{object_name}"
            if object_name
            else type(current).__name__
        )
        chain.append(label)
        if root is not None and current is root:
            break
        current = current.parentWidget()
    return " > ".join(reversed(chain))


def audit_widget_tree(
    root: QWidget,
    *,
    tokens: ThemeTokens | None = None,
    widget_rules: tuple[rules.A11yRule, ...] = rules.DEFAULT_RULES,
) -> list[A11yFinding]:
    """Walk every widget under ``root`` (inclusive) and return every finding.

    Args:
        root: The widget to start from -- typically a fully populated
            :class:`~src.ui.main_window.MainWindow`, so the audit sees
            everything a real session would construct: menu bar, toolbar,
            docks, every workbench stage page, and any dialog currently
            parented to it (see :class:`~src.ui.command_palette.
            CommandPalette`, constructed once at startup with ``root`` as its
            Qt parent, which is why it -- unlike on-demand dialogs such as
            :class:`~src.ui.dialogs.settings_dialog.SettingsDialog` -- is
            reachable from this walk without being separately opened).
        tokens: The currently applied theme's tokens, for the contrast rule.
            ``None`` skips contrast checking entirely rather than assuming a
            theme -- a caller auditing a bare, theme-less test widget should
            not get spurious contrast findings against colors that were
            never actually applied.
        widget_rules: The rule set to run. Defaults to
            :data:`~src.ui.a11y.rules.DEFAULT_RULES`; overridable so a
            focused test can run a single rule in isolation.

    Returns:
        Every finding from every rule, root-first in tree order for the
        per-widget rules, followed by any tree-wide findings (duplicate
        shortcuts, contrast) that are not attributable to walk order at all.

    ``QWidget.findChildren`` walks the full Qt object tree regardless of
    visibility -- a hidden ``QStackedWidget`` page still has real, constructed
    widgets a user reaches by clicking through to it, and those need the same
    scrutiny as whatever happens to be on screen at audit time. Filtering to
    ``isVisible()`` widgets only would silently exempt every workbench stage
    page except the one currently shown.
    """
    all_widgets: list[QWidget] = [root, *root.findChildren(QWidget)]
    findings: list[A11yFinding] = []
    for rule in widget_rules:
        findings.extend(rule.check(root, all_widgets))
    if tokens is not None:
        findings.extend(rules.contrast_findings(tokens))
    return findings


def _discover_dialog_classes() -> tuple[type[QDialog], ...]:
    """Import every module under :mod:`src.ui` and collect ``QDialog`` subclasses defined there.

    Hand-maintaining a dialog list (as this project's own M28 plan section
    calls out) drifts the moment a dialog is added or renamed and nobody
    remembers to update the list -- this instead re-derives it from the
    actual module tree every time it is imported, the same "single source of
    truth" reasoning behind :data:`~src.visualization.chart_registry`'s
    registry pattern, just via introspection instead of an explicit
    ``register_x`` call (a ``QDialog`` subclass needs no registration
    decision the way a chart type does -- being a ``QDialog`` at all is
    already the complete signal).

    Only classes *defined* in the module being inspected are kept
    (``obj.__module__ == module.__name__``), not re-exported imports of
    ``QDialog`` itself or of another module's dialog class -- otherwise
    ``QDialog`` and every dialog would be double-counted once per module that
    merely imports it.

    A module that fails to import (this codebase has none that do at present
    -- confirmed empirically while building this function -- but a future
    module could conceivably gain a real import-time dependency this
    environment lacks) is skipped with a warning rather than raising, so one
    broken module cannot take down every other dialog's discoverability.
    """
    discovered: list[type[QDialog]] = []
    for module_info in pkgutil.walk_packages([str(_SRC_UI_DIR)], prefix="src.ui."):
        try:
            module = importlib.import_module(module_info.name)
        except Exception as exc:  # pragma: no cover - defensive, see docstring
            _logger.warning(
                "Skipped '%s' while discovering QDialog subclasses: %s",
                module_info.name,
                exc,
            )
            continue
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, QDialog)
                and obj is not QDialog
                and obj.__module__ == module.__name__
            ):
                discovered.append(obj)
    # Sorted by qualified name for a stable, diffable order -- pkgutil's walk
    # order depends on filesystem iteration order, which is not guaranteed
    # across platforms.
    discovered.sort(key=lambda cls: f"{cls.__module__}.{cls.__qualname__}")
    return tuple(discovered)


# Built at import time, matching how src.visualization.chart_registry's own
# built-in registrations are populated at import time -- a dialog class is
# either defined somewhere under src/ui/ or it is not, and that does not
# change over the life of a running process. Recomputing this from scratch
# is not free (it imports every src.ui module), so this module-level constant
# is what callers should read; call _discover_dialog_classes() directly only
# from a test that specifically wants to prove the discovery mechanism works.
ALL_DIALOG_CLASSES: tuple[type[QDialog], ...] = _discover_dialog_classes()
