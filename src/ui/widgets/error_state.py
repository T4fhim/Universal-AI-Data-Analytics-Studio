# File: src/ui/widgets/error_state.py
"""``ErrorState``: a persistent, in-page alternative to ``QMessageBox.critical`` (milestone 27).

Before this milestone, every workbench stage page routed a failed tool call straight to a
modal ``QMessageBox.critical`` -- see ``clean_page.py``, ``explore_page.py``, ``analyze_page.py``,
``predict_page.py``, ``visualize_page.py``. A modal dialog is the right shape for a genuinely
transient, one-shot failure (a file that will not open, a database connection that will not
establish -- see the dialogs/controllers this milestone deliberately leaves alone, listed in
its own plan entry), but a *stage page* failure is different: the page itself stays visible and
re-usable afterward (the user can change parameters and press Run again), so the failure is
part of that page's persistent state, not a one-shot interruption that goes away the moment the
dialog is dismissed. :class:`ErrorState` gives that persistent state a real, in-page home --
shown in place of (or alongside) the page's result area until the next successful run replaces
it, rather than flashing a dialog the user may not have even finished reading before it closes.

Structurally a near-twin of :class:`~src.ui.widgets.empty_state.EmptyState` (illustration +
heading + message + one optional action button) -- deliberately not unified into one class with
a "kind" flag, because the two need different default illustrations/object names for QSS
targeting and a shared base class would save only a few lines at the cost of a
harder-to-read constructor signature. See that module's own docstring for the illustration
rendering and accessibility rationale, both reused here unchanged.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from src.ui.a11y.accessible import describe
from src.ui.theme.tokens import DARK_TOKENS
from src.ui.widgets.empty_state import render_illustration


class ErrorState(QWidget):
    """Illustration + heading + error message + one optional retry/dismiss action.

    Args:
        heading: Short statement of what failed -- "Exploration Failed", matching the same
            title text the ``QMessageBox.critical`` calls this widget replaces already used,
            so the user-facing wording does not change, only its persistence and placement.
        message: The error detail -- typically ``str(exc)`` from the caught exception, the same
            text the replaced dialog's body already showed.
        illustration: Filename stem under ``resources/icons/illustrations/`` (no extension).
        action_text: Label for an optional retry/dismiss button. ``None`` (the default) shows
            no button -- most call sites this milestone converts have no meaningful "retry"
            distinct from just pressing the page's own Run button again, so forcing one here
            would duplicate it.
        parent: Optional parent widget.

    Signals:
        action_triggered: Emitted when the optional action button is clicked -- same
            plain-signal shape :class:`~src.ui.widgets.empty_state.EmptyState.action_triggered`
            uses, for the same reason (the caller, not this widget, knows what "retry" means).
    """

    action_triggered = Signal()

    def __init__(
        self,
        *,
        heading: str,
        message: str,
        illustration: str = "error-circle",
        action_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("errorState")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        # DARK_TOKENS.danger, not text_secondary -- an error illustration is allowed to read as
        # visually distinct from an empty state's neutral one, and this project's "never
        # color-only" a11y rule is about not relying on color *alone* to carry meaning, not
        # about avoiding color as a reinforcing signal (the heading text already says "Failed").
        self._illustration_label = QLabel(self)
        self._illustration_label.setObjectName("errorStateIllustration")
        self._illustration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._illustration_label.setPixmap(
            render_illustration(illustration, DARK_TOKENS.danger)
        )
        describe(
            self._illustration_label,
            name=self.tr("{0} illustration").format(heading),
            description=self.tr("Illustration accompanying an error: {0}").format(
                heading
            ),
            focusable=False,
        )
        layout.addWidget(self._illustration_label)

        self._heading_label = QLabel(heading, self)
        self._heading_label.setObjectName("errorStateHeading")
        self._heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._heading_label.setWordWrap(True)
        layout.addWidget(self._heading_label)

        self._message_label = QLabel(message, self)
        self._message_label.setObjectName("errorStateMessage")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._message_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._message_label)

        self.action_button: QPushButton | None = None
        if action_text:
            self.action_button = QPushButton(action_text, self)
            self.action_button.setObjectName("errorStateActionButton")
            describe(self.action_button, name=action_text)
            self.action_button.clicked.connect(self.action_triggered)
            layout.addWidget(self.action_button)

        describe(self, name=heading, description=message, focusable=False)

    def set_error(self, heading: str, message: str) -> None:
        """Replace the heading/message text -- for a page that reuses one instance across runs."""
        self._heading_label.setText(heading)
        self._message_label.setText(message)
        describe(self, name=heading, description=message, focusable=False)
