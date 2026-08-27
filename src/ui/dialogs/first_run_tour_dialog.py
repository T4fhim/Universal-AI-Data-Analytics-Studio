# File: src/ui/dialogs/first_run_tour_dialog.py
"""A one-time onboarding tour, shown before this milestone ``ui.first_run_completed`` existed.

**Dismissible, and shown only once, by construction rather than by any state this dialog itself
tracks.** This class has no notion of "have I been shown before" at all -- it does not read or
write ``ui.first_run_completed``, and never will; deciding *whether* to construct and show it,
and marking it seen afterward, is :func:`src.core.app.Application.run`'s job (the composition
root, the one place :data:`~src.core.config.AppConfig.ui_first_run_completed` is read and
:class:`~src.services.settings_service.SettingsService` is available before
:class:`~src.ui.main_window.MainWindow` is fully constructed). Any way of closing this dialog --
the Close button, the window's own close control, Escape -- counts as "dismissed"; there is no
separate "don't show again" checkbox to miss, since showing it at all already means the answer
to "should this reappear" is unconditionally no.

Modal, unlike :class:`~src.ui.dialogs.manual_dialog.ManualDialog` -- a one-time orientation
screen shown once, at the very start of a session, is exactly the "read this before continuing"
case a modal dialog is for, unlike ongoing reference material meant to be consulted mid-work.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.constants import APP_NAME
from src.core.logger import get_logger
from src.ui.a11y.accessible import describe

_logger = get_logger(__name__)

_BODY_HTML = """
<p>A few things worth knowing before you start:</p>
<ul>
<li><b>The guided pipeline.</b> The stage rail on the left walks a dataset through ten fixed
stages -- Upload, Understand, Clean, Explore, Analyze, Visualize, Predict, Explain, Report,
Reproduce -- always in that order. Nothing forces you through them in sequence; the guidance
panel on each stage page only ever <i>suggests</i> what to try next.</li>
<li><b>Press F1 anywhere</b> to open the manual section for whatever has focus.</li>
<li><b>The AI assistant is entirely optional.</b> Every stage's core functionality works with
no API key configured at all -- the assistant only adds a chat-based way to reach the same
tools, plus plain-language explanations of results on the Explain stage.</li>
</ul>
<p>This won't be shown again.</p>
"""


class FirstRunTourDialog(QDialog):
    """A short, modal, one-time orientation screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        body = QLabel(self)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setText(_BODY_HTML)
        describe(
            body,
            name="First-run tour",
            description="A short orientation to the guided pipeline, F1 help, and the "
            "optional AI assistant.",
            focusable=False,
        )
        layout.addWidget(body)

        close_button = QPushButton("Get Started", self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)

        _logger.debug("First-run tour dialog constructed.")
