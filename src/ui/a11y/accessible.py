# File: src/ui/a11y/accessible.py
"""One call to make a widget accessible, so it is never skipped by accident.

Qt 6 on Windows exposes widgets through the UI Automation backend, so a
standard widget is *reachable* by a screen reader for free. Reachable is not
the same as usable: without an accessible name, a screen reader announces a
``QPushButton`` carrying only an icon as "button", and a ``QLineEdit`` in a
form as "edit" -- technically present, practically unusable.

:func:`describe` sets the five properties that turn a reachable widget into a
usable one, in a single call, because five separate calls at every
construction site is exactly the friction that produced the current state of
the codebase: thirteen accessibility calls in ~10,000 lines.

It also stamps a ``helpAnchor`` dynamic property, which
:func:`src.ui.help.help_router.resolve_help_anchor` (milestone 27) walks up
the parent chain to answer F1. Putting it here rather than in the help module
means a widget gets context-sensitive help by virtue of being described,
rather than by being separately registered somewhere it can be forgotten.

Free functions rather than a mixin -- see this package's ``__init__`` for why.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtWidgets import QLabel, QWidget

from src.core.logger import get_logger

_logger = get_logger(__name__)

# The dynamic-property key the help router reads. A module constant so the
# two modules cannot disagree about the spelling.
HELP_ANCHOR_PROPERTY = "helpAnchor"


def describe(
    widget: QWidget,
    *,
    name: str,
    description: str | None = None,
    status_tip: str | None = None,
    tooltip: str | None = None,
    help_anchor: str | None = None,
    focusable: bool = True,
) -> None:
    """Make ``widget`` announceable, hoverable, and reachable by keyboard.

    Args:
        widget: The widget to describe.
        name: Short accessible name -- what a screen reader says when focus
            arrives. Required, and required to be non-empty: an empty name is
            the single most common accessibility defect, and defaulting it
            would let it pass silently.
        description: Longer explanation of what the control does. Also used
            as the tooltip when ``tooltip`` is not given, so that sighted and
            screen-reader users get the same explanation rather than two that
            drift apart.
        status_tip: Text for the status bar on hover or focus.
        tooltip: Overrides ``description`` for the hover tooltip, for the rare
            case where the two genuinely should differ.
        help_anchor: Manual anchor F1 should open from this widget.
        focusable: When ``True`` (the default) a widget with
            ``Qt.NoFocus`` is promoted to ``Qt.StrongFocus``. Pass ``False``
            for genuinely non-interactive decoration. An existing non-``NoFocus``
            policy is never overwritten -- a widget that deliberately chose
            ``ClickFocus`` keeps it.

    Raises:
        ValueError: If ``name`` is empty or whitespace.
    """
    if not name or not name.strip():
        raise ValueError(
            f"describe() requires a non-empty accessible name for "
            f"{type(widget).__name__}. An unnamed interactive widget is "
            f"announced only by its role ('button', 'edit')."
        )

    widget.setAccessibleName(name)
    if description:
        widget.setAccessibleDescription(description)
    if status_tip:
        widget.setStatusTip(status_tip)

    resolved_tooltip = tooltip if tooltip is not None else description
    if resolved_tooltip:
        widget.setToolTip(resolved_tooltip)

    if help_anchor:
        widget.setProperty(HELP_ANCHOR_PROPERTY, help_anchor)

    if focusable and widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


def label_for(field: QWidget, label: QLabel, *, name: str | None = None) -> None:
    """Associate ``label`` with ``field`` as its caption.

    ``QLabel.setBuddy`` gives Qt the pairing -- which makes the label's ``&``
    mnemonic move focus to the field -- but does **not** set the field's
    accessible name on every platform. So this mirrors the label text across
    explicitly rather than trusting the buddy relationship to carry it.

    Args:
        field: The input widget.
        label: Its caption.
        name: Overrides the derived name. By default the label's text is used
            with any ``&`` mnemonic marker and trailing colon stripped, so
            ``"&Host:"`` becomes ``"Host"``.
    """
    label.setBuddy(field)
    derived = name or label.text().replace("&", "").rstrip(":").strip()
    if derived:
        field.setAccessibleName(derived)


def set_tab_order(*widgets: QWidget) -> None:
    """Chain ``widgets`` into an explicit keyboard tab order.

    Qt's default tab order follows construction order, which stops matching
    the visual order as soon as a widget is added to a layout out of sequence
    or a form is rearranged. That produces a focus path that jumps around the
    dialog -- operable, but disorienting, and a WCAG 2.4.3 (Focus Order)
    failure.

    Fewer than two widgets is a silent no-op rather than an error, so callers
    can pass a list built conditionally without guarding.
    """
    for previous, following in zip(widgets, widgets[1:]):
        QWidget.setTabOrder(previous, following)


def announce(widget: QWidget, message: str) -> None:
    """Speak ``message`` through the screen reader without moving focus.

    The equivalent of an ARIA live region. Needed because the most important
    things this application says -- "analysis complete", "3 datasets skipped"
    -- happen asynchronously, and a screen-reader user who is not focused on
    the status bar would otherwise never learn about them.

    Implemented by setting the accessible *description* and posting a
    ``DescriptionChanged`` event. Qt has no dedicated live-region API, and
    changing the accessible *name* instead was rejected: the name is what
    identifies the control, so overwriting it would rename the widget every
    time it had something to report.
    """
    if not message:
        return
    widget.setAccessibleDescription(message)
    QAccessible.updateAccessibility(
        QAccessibleEvent(widget, QAccessible.Event.DescriptionChanged)
    )
    _logger.debug("Announced to accessibility clients: %s", message)
