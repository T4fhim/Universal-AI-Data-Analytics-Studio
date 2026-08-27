# File: src/ui/a11y/rules.py
"""The concrete WCAG 2.2 AA checks :func:`~src.ui.a11y.audit.audit_widget_tree` runs.

Each rule is a small, independently testable function of "the widgets found
under some root" (or, for :func:`contrast_findings`, "the currently applied
theme's tokens") to a list of :class:`A11yFinding`. Kept in a separate module
from :mod:`src.ui.a11y.audit` (rather than as private functions there) for
the same reason :mod:`src.ui.a11y.contrast_manifest` is separate from
:mod:`src.ui.theme.contrast`: the *math*/walking machinery and the *list of
things actually checked* change for different reasons and at different
rates, and a new rule should be addable by reading and extending this file
alone.

**Why not a mutable registry like** :mod:`src.visualization.chart_registry`
**.** This project's own convention (see this repo's cross-cutting rule 3)
is for new registries to mirror that shape -- a frozen registration
dataclass, a module dict, ``register_x`` raising on duplicates, ``get_x``/
``list_x``/``unregister_x``. That shape exists to let *third parties*
(plugins) extend a registry at runtime. Nothing here needs that: the rule set
is a fixed, exhaustively-enumerable list of WCAG checks this application
itself implements, not user- or plugin-extensible content the way a chart
type or a cleaning operation is. A plain tuple of :class:`A11yRule` is the
honest shape for that, and does not force every consumer to import a
registration API three functions deep purely to read a constant list.

Each ``check`` receives ``(root, all_widgets)`` -- the tree :func:`~src.ui.
a11y.audit.audit_widget_tree` already walked once, handed to every rule
rather than re-walked per rule, so adding a tenth rule does not add a tenth
full-tree traversal.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDockWidget,
    QLabel,
    QLineEdit,
    QScrollBar,
    QTabBar,
    QToolBar,
    QToolButton,
    QWidget,
)

from src.ui.a11y.contrast_manifest import CONTRAST_REQUIREMENTS
from src.ui.theme.contrast import contrast_ratio
from src.ui.theme.tokens import ThemeTokens


class Severity(str, Enum):
    """How seriously a finding should be treated.

    Subclasses ``str`` for the same reason
    :class:`~src.core.expertise_level.ExpertiseLevel` and
    :class:`~src.ui.theme.tokens.Density` do -- it prints and compares
    cleanly in test failure output and log lines with no extra conversion.

    ``ERROR`` is a real WCAG 2.2 AA failure: something an assistive
    technology user cannot do at all (reach a control, read a value,
    distinguish a state). ``WARNING`` is a defect worth fixing that does not
    itself block the M28 "zero ERROR findings" acceptance gate -- a coarse
    heuristic (like the tab-order check below) that can have false
    positives, or a completeness gap (a decorative label with no
    description) that degrades rather than blocks the experience.
    """

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class A11yFinding:
    """One accessibility defect found by a rule below.

    Attributes:
        severity: :class:`Severity`.
        rule_id: The originating :attr:`A11yRule.rule_id`, so a failing test
            names *which* rule fired, not just a bare message.
        widget_path: A human-readable ancestor-chain path locating the
            widget, built by :func:`~src.ui.a11y.audit.describe_widget`.
        message: What is wrong, specific enough to act on without re-reading
            the rule's own docstring.
    """

    severity: Severity
    rule_id: str
    widget_path: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        return (
            f"[{self.severity.value.upper()}] {self.rule_id}: "
            f"{self.widget_path} -- {self.message}"
        )


CheckFunction = Callable[[QWidget, list[QWidget]], list[A11yFinding]]


@dataclass(frozen=True)
class A11yRule:
    """One check :func:`~src.ui.a11y.audit.audit_widget_tree` runs against a widget tree.

    Attributes:
        rule_id: Short, stable identifier -- appears in every
            :attr:`A11yFinding.rule_id` this rule produces, and is what a
            caller passes to :meth:`~src.ui.a11y.audit.audit_widget_tree`'s
            ``widget_rules`` to run one rule in isolation.
        description: One line explaining what the rule enforces and, where
            relevant, which WCAG 2.2 success criterion it covers.
        check: The function itself. Takes ``(root, all_widgets)`` -- the
            already-walked tree -- rather than walking again, so N rules cost
            one traversal, not N.
    """

    rule_id: str
    description: str
    check: CheckFunction


def _path(widget: QWidget, root: QWidget) -> str:
    """Local alias for :func:`~src.ui.a11y.audit.describe_widget`.

    A plain module-level import of ``src.ui.a11y.audit`` here would create
    the same circular import :mod:`src.ui.a11y.audit` itself documents
    avoiding (that module imports *this* one for the rule set) -- so the tiny
    amount of path-building logic that both modules need is duplicated
    rather than shared, which is cheaper than restructuring either module
    around a shared third module for four lines of string-joining.
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
        if current is root:
            break
        current = current.parentWidget()
    return " > ".join(reversed(chain))


def _is_qt_private(widget: QWidget) -> bool:
    """Whether ``widget`` is Qt's own composite-control chrome, not app-authored content.

    Two cases, both empirically confirmed while building this rule set rather
    than assumed:

    1. A ``QComboBox``'s internal line edit, a ``QSpinBox``'s up/down
       buttons, a ``QScrollBar``'s arrow buttons -- Qt assigns these an
       ``objectName`` conventionally prefixed ``qt_``. They are
       implementation detail of a single already-checked parent widget, not
       independently reachable controls a rule should evaluate on their own
       terms.
    2. ``QLineEdit.setClearButtonEnabled`` (used by ``src/ui/widgets/
       data_table/filter_bar.py``) creates an internal ``QToolButton`` bound
       to a ``QAction`` Qt itself names ``_q_qlineeditclearaction`` -- no
       ``qt_``-prefixed ``objectName`` this time, and the button itself is
       unnamed, with no public Qt API to attach one (no
       ``QLineEdit.clearButton()`` accessor exists). Not a functional gap
       regardless: the identical "clear the field" action remains fully
       keyboard-reachable through the field itself (select-all + delete).
    """
    if widget.objectName().startswith("qt_"):
        return True
    if isinstance(widget, QToolButton):
        default_action = widget.defaultAction()
        if default_action is not None and default_action.objectName().startswith("_q_"):
            return True
    return False


def _is_toolbar_button(widget: QWidget) -> bool:
    """Whether ``widget`` is a ``QToolButton`` Qt attached to a ``QToolBar``.

    A second, deliberate exclusion from the ``focus-reachable``/
    ``tab-order`` checks specifically (not from ``interactive-name`` -- a
    toolbar button still needs a real name). Qt defaults every
    ``QToolButton`` a ``QToolBar.addAction`` creates to ``Qt.NoFocus``
    (confirmed directly, not assumed), matching the platform convention that
    a toolbar is a mouse accelerator for actions already fully
    keyboard-operable elsewhere. This application's own architecture makes
    that guarantee concrete rather than aspirational: see ``src/ui/actions/
    action_binder.py``'s own docstring -- "the menu bar, the toolbar, and the
    command palette all share the *same* QAction object for a given
    action_id" -- so every toolbar button's action remains reachable via the
    menu bar's mnemonics and the command palette (Ctrl+K) regardless of
    whether the toolbar button itself is a Tab stop.
    """
    return isinstance(widget, QToolButton) and isinstance(
        widget.parentWidget(), QToolBar
    )


# -- Rule: every button-like control has a name, from its own text or an explicit one ----------

_BUTTON_LIKE = (QAbstractButton,)


def _check_button_names(root: QWidget, all_widgets: list[QWidget]) -> list[A11yFinding]:
    findings: list[A11yFinding] = []
    for widget in all_widgets:
        if not isinstance(widget, _BUTTON_LIKE) or _is_qt_private(widget):
            continue
        has_name = bool(widget.accessibleName().strip()) or bool(widget.text().strip())
        if not has_name:
            findings.append(
                A11yFinding(
                    Severity.ERROR,
                    "interactive-name",
                    _path(widget, root),
                    "Button-like control has neither visible text nor an "
                    "accessible name -- a screen reader announces only its "
                    "role (e.g. 'button'). Call src.ui.a11y.accessible."
                    "describe() with a name, or set text().",
                )
            )
    return findings


# -- Rule: every text/selection input has a name, from a buddy label or an explicit one --------

_FIELD_LIKE = (QLineEdit, QComboBox, QAbstractSpinBox, QAbstractSlider)


def _has_buddy_label(widget: QWidget, all_widgets: list[QWidget]) -> bool:
    return any(
        isinstance(candidate, QLabel) and candidate.buddy() is widget
        for candidate in all_widgets
    )


def _check_field_names(root: QWidget, all_widgets: list[QWidget]) -> list[A11yFinding]:
    findings: list[A11yFinding] = []
    for widget in all_widgets:
        if not isinstance(widget, _FIELD_LIKE) or _is_qt_private(widget):
            continue
        # QScrollBar is a QAbstractSlider, but the scrollbars Qt attaches to
        # every QAbstractScrollArea (a tree view, a chat message list, a
        # code editor) are structural chrome, not an app-authored control
        # with a distinct purpose -- their role alone ("scroll bar") is
        # already what a screen reader announces, and no accessibility
        # guideline expects an app to separately name "the vertical
        # scrollbar of this list". A genuinely custom-purpose slider (a
        # "volume" or "opacity" control) is not a QScrollBar and is still
        # covered by this rule.
        if isinstance(widget, QScrollBar):
            continue
        has_name = bool(widget.accessibleName().strip()) or _has_buddy_label(
            widget, all_widgets
        )
        if not has_name:
            findings.append(
                A11yFinding(
                    Severity.ERROR,
                    "input-buddy",
                    _path(widget, root),
                    "Input control has neither a buddy QLabel "
                    "(QLabel.setBuddy / src.ui.a11y.accessible.label_for) "
                    "nor an explicit accessible name -- its purpose is "
                    "unannounced.",
                )
            )
    return findings


# -- Rule: no interactive widget is unreachable by keyboard -------------------------------------

_INTERACTIVE = (*_BUTTON_LIKE, *_FIELD_LIKE, QTabBar)


def _check_focus_reachable(
    root: QWidget, all_widgets: list[QWidget]
) -> list[A11yFinding]:
    findings: list[A11yFinding] = []
    for widget in all_widgets:
        if not isinstance(widget, _INTERACTIVE) or _is_qt_private(widget):
            continue
        # See _check_field_names' own comment: a QAbstractScrollArea's
        # attached QScrollBar is structural chrome, not an app-authored
        # control -- its default focus policy (which varies by platform
        # style) is not this application's decision to make or flag.
        if isinstance(widget, QScrollBar):
            continue
        # See _is_toolbar_button's own comment: this application's
        # ActionBinder guarantees the same QAction (and therefore the same
        # functionality) is reachable via the menu bar and command palette
        # regardless of the toolbar button's own focus policy.
        if _is_toolbar_button(widget):
            continue
        if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
            findings.append(
                A11yFinding(
                    Severity.ERROR,
                    "focus-reachable",
                    _path(widget, root),
                    "Interactive widget has Qt.NoFocus and cannot be "
                    "reached by Tab -- keyboard-only operation is "
                    "impossible for this control (WCAG 2.1.1).",
                )
            )
    return findings


# -- Rule: dialogs offer at least one keyboard-reachable control (a bare-minimum focus-trap check) --


def _check_dialog_not_a_trap(
    root: QWidget, all_widgets: list[QWidget]
) -> list[A11yFinding]:
    """Flag a ``QDialog`` with real content but nothing a keyboard can reach.

    This is a floor, not a full focus-trap audit (proving a trap requires
    actually driving Tab/Shift+Tab through a shown window and watching where
    focus lands, which needs a live event loop and is out of reach for a
    static tree walk). What *is* staticaly checkable, and worth checking, is
    the degenerate case: a dialog that was given content but where none of
    it can ever receive keyboard focus is unusable by keyboard from the
    moment it opens, regardless of how Tab behaves once inside it.
    """
    findings: list[A11yFinding] = []
    for widget in all_widgets:
        if not isinstance(widget, QDialog):
            continue
        descendants = widget.findChildren(QWidget)
        if not descendants:
            continue  # an empty/placeholder dialog has nothing to trap focus in
        any_focusable = any(
            child.focusPolicy() != Qt.FocusPolicy.NoFocus and not _is_qt_private(child)
            for child in descendants
        )
        if not any_focusable:
            findings.append(
                A11yFinding(
                    Severity.ERROR,
                    "dialog-focus-trap",
                    _path(widget, root),
                    "Dialog has content but no keyboard-focusable widget -- "
                    "a keyboard-only user cannot interact with it at all "
                    "once it opens (WCAG 2.1.1/2.1.2).",
                )
            )
    return findings


# -- Rule: no ambiguous duplicate keyboard shortcuts ---------------------------------------------


def _check_duplicate_shortcuts(
    root: QWidget, all_widgets: list[QWidget]
) -> list[A11yFinding]:
    """Flag a window/application-scoped shortcut bound to more than one action.

    Only ``QAction``/``QShortcut`` whose context reaches beyond the widget
    that owns them are considered -- a ``Qt.WidgetShortcut`` scoped to one
    control cannot conflict with anything outside it by construction, so
    including those would produce false positives for legitimate per-widget
    bindings (e.g. the same arrow-key behavior reimplemented locally in two
    unrelated custom widgets).
    """
    findings: list[A11yFinding] = []
    seen: dict[str, list[str]] = {}

    def _record(sequence_text: str, label: str, context: Qt.ShortcutContext) -> None:
        if not sequence_text or context == Qt.ShortcutContext.WidgetShortcut:
            return
        seen.setdefault(sequence_text, []).append(label)

    for action in root.findChildren(QAction):
        sequence = action.shortcut()
        if not sequence.isEmpty():
            _record(
                sequence.toString(),
                action.text() or action.objectName() or "<unnamed action>",
                action.shortcutContext(),
            )
    for shortcut in root.findChildren(QShortcut):
        sequence = shortcut.key()
        if not sequence.isEmpty():
            _record(
                sequence.toString(),
                shortcut.objectName() or "<unnamed shortcut>",
                shortcut.context(),
            )

    for sequence_text, labels in seen.items():
        if len(labels) > 1:
            findings.append(
                A11yFinding(
                    Severity.ERROR,
                    "duplicate-shortcut",
                    _path(root, root),
                    f"Shortcut '{sequence_text}' is bound to more than one "
                    f"action/shortcut with window-or-wider scope: "
                    f"{', '.join(labels)}.",
                )
            )
    return findings


# -- Rule: every dock has a real window title -----------------------------------------------------


def _check_dock_titles(root: QWidget, all_widgets: list[QWidget]) -> list[A11yFinding]:
    findings: list[A11yFinding] = []
    for widget in all_widgets:
        if isinstance(widget, QDockWidget) and not widget.windowTitle().strip():
            findings.append(
                A11yFinding(
                    Severity.ERROR,
                    "dock-title",
                    _path(widget, root),
                    "QDockWidget has no window title -- announced to a "
                    "screen reader (and shown in the View menu) with no "
                    "identifying name.",
                )
            )
    return findings


# -- Rule: decorative illustrations still carry an accessible description ------------------------


def _check_illustration_descriptions(
    root: QWidget, all_widgets: list[QWidget]
) -> list[A11yFinding]:
    """Flag a pixmap-only ``QLabel`` with no accessible name or description.

    WCAG's usual guidance for a purely decorative image is to hide it from
    assistive technology entirely (an empty ``alt``). This codebase makes a
    different, deliberate choice (see ``src/ui/widgets/empty_state.py``'s own
    docstring): illustrations here accompany empty/error states and are
    reinforcing content, not filler, so the rule is "describe it", not "hide
    it" -- a label carrying only a pixmap and nothing else is the specific
    defect this checks for.
    """
    findings: list[A11yFinding] = []
    for widget in all_widgets:
        if not isinstance(widget, QLabel):
            continue
        pixmap = widget.pixmap()
        if pixmap is None or pixmap.isNull():
            continue
        if widget.accessibleName().strip() or widget.accessibleDescription().strip():
            continue
        findings.append(
            A11yFinding(
                Severity.WARNING,
                "decorative-illustration",
                _path(widget, root),
                "QLabel renders an image but has no accessible name or "
                "description -- a screen reader user gets no indication of "
                "what it depicts. Call src.ui.a11y.accessible.describe().",
            )
        )
    return findings


# -- Rule: tab order is not degenerate (coarse heuristic; see docstring) -------------------------


def _check_tab_order_nondegenerate(
    root: QWidget, all_widgets: list[QWidget]
) -> list[A11yFinding]:
    """Flag a tree where two or more interactive widgets exist but the focus chain never leaves one.

    A genuine, precise focus-order audit (WCAG 2.4.3) requires driving Tab
    through a *shown* window and observing where focus actually lands each
    time -- unavailable to a static tree walk against a window that may not
    even be shown (as in an offscreen test run). ``QWidget.nextInFocusChain``
    is at least real Qt state, not a heuristic invented here, so this walks
    it from ``root`` and flags the one case a static walk genuinely can
    catch with no false-positive risk: a chain that never advances past its
    own starting point despite multiple interactive widgets existing in the
    tree, which is a hard structural break (an isolated island of widgets
    Tab literally cannot reach), not a matter of what order things happen to
    be in. Severity is ``WARNING``, not ``ERROR``, precisely because the
    positive case (a non-degenerate chain) is not proof the *order* is
    sensible, only that it is not completely broken.
    """
    interactive_count = sum(
        1
        for widget in all_widgets
        if isinstance(widget, _INTERACTIVE)
        and not _is_qt_private(widget)
        and not isinstance(widget, QScrollBar)
        and not _is_toolbar_button(widget)
        and widget.focusPolicy() != Qt.FocusPolicy.NoFocus
    )
    if interactive_count < 2:
        return []

    visited: set[int] = set()
    current = root.nextInFocusChain()
    steps = 0
    while current is not None and id(current) not in visited and steps < 2000:
        visited.add(id(current))
        current = current.nextInFocusChain()
        steps += 1

    if len(visited) <= 1:
        return [
            A11yFinding(
                Severity.WARNING,
                "tab-order",
                _path(root, root),
                f"{interactive_count} focusable interactive widgets exist "
                "under this root, but QWidget.nextInFocusChain() never "
                "advances past a single widget -- the tab chain may be "
                "structurally broken (WCAG 2.4.3).",
            )
        ]
    return []


DEFAULT_RULES: tuple[A11yRule, ...] = (
    A11yRule(
        "interactive-name",
        "Every button-like control has visible text or an accessible name.",
        _check_button_names,
    ),
    A11yRule(
        "input-buddy",
        "Every QLineEdit/QComboBox/QAbstractSpinBox/QAbstractSlider has a "
        "buddy label or an accessible name.",
        _check_field_names,
    ),
    A11yRule(
        "focus-reachable",
        "No interactive widget has Qt.NoFocus.",
        _check_focus_reachable,
    ),
    A11yRule(
        "dialog-focus-trap",
        "Every non-empty QDialog has at least one keyboard-focusable widget.",
        _check_dialog_not_a_trap,
    ),
    A11yRule(
        "duplicate-shortcut",
        "No window-or-wider-scoped keyboard shortcut is bound twice.",
        _check_duplicate_shortcuts,
    ),
    A11yRule(
        "dock-title",
        "Every QDockWidget has a non-empty window title.",
        _check_dock_titles,
    ),
    A11yRule(
        "decorative-illustration",
        "Every pixmap-only QLabel has an accessible name or description.",
        _check_illustration_descriptions,
    ),
    A11yRule(
        "tab-order",
        "The keyboard focus chain is not structurally degenerate.",
        _check_tab_order_nondegenerate,
    ),
)


def contrast_findings(tokens: ThemeTokens) -> list[A11yFinding]:
    """Check every :data:`~src.ui.a11y.contrast_manifest.CONTRAST_REQUIREMENTS` pairing against ``tokens``.

    Not part of :data:`DEFAULT_RULES` -- every rule above is a function of a
    walked widget tree, while this is a function of a *theme*, entirely
    independent of which widgets happen to exist. Called directly by
    :func:`~src.ui.a11y.audit.audit_widget_tree` when a caller passes
    ``tokens``, so an audit against a live, themed application still reports
    contrast failures alongside structural ones in one combined list.

    Reuses :func:`~src.ui.theme.contrast.contrast_ratio` and the exact
    requirement list ``tests/ui/theme/test_contrast.py`` already asserts
    against every theme (see that module and :mod:`src.ui.a11y.
    contrast_manifest`) -- this function exists so the same guarantee is
    available at audit time, not just at test time, without re-deriving the
    pairing list or the WCAG math a second time.
    """
    findings: list[A11yFinding] = []
    for requirement in CONTRAST_REQUIREMENTS:
        foreground = getattr(tokens, requirement.foreground)
        background = getattr(tokens, requirement.background)
        ratio = contrast_ratio(foreground, background)
        if ratio < requirement.minimum:
            findings.append(
                A11yFinding(
                    Severity.ERROR,
                    "contrast",
                    f"ThemeTokens('{tokens.name}')",
                    f"{requirement.rationale}: {requirement.foreground} "
                    f"({foreground}) on {requirement.background} "
                    f"({background}) is {ratio:.2f}:1, below the required "
                    f"{requirement.minimum}:1.",
                )
            )
    return findings
