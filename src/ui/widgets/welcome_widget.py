# File: src/ui/widgets/welcome_widget.py
"""The central widget shown when no project is currently open.

:class:`WelcomeWidget` is deliberately simple in this milestone: a
title, a subtitle, and two buttons (New Project, Open Project) whose
actual behavior is wired by :mod:`src.ui.main_window` rather than
implemented here — matching the same "structure here, behavior wired
by the caller" pattern used for the menu bar's actions. A richer
welcome screen (recent-project thumbnails, a getting-started guide) is
plausible future work but is not part of this milestone's scope.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.constants import APP_NAME
from src.core.logger import get_logger
from src.ui.a11y.accessible import describe

_logger = get_logger(__name__)


class WelcomeWidget(QWidget):
    """The application's welcome screen, shown when no project is open.

    After construction, connect :attr:`button_new_project` and
    :attr:`button_open_project` to real handlers — this class only
    builds the buttons, it does not decide what clicking them does.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcomeWidget")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        title_label = QLabel(f"Welcome to {APP_NAME}")
        title_label.setObjectName("welcomeTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Unit 5 (UI-friendliness pass): neither label needed describe() to pass the a11y
        # audit (a text-bearing QLabel already exposes its own text() as an accessible
        # name -- audit.py's pixmap-only-QLabel rule is the actual gap that check closes),
        # but StagePage's own _guidance_label sets exactly this precedent already: a
        # curated name plus focusable=False (a label to read, not a control to tab to) is
        # friendlier to a screen reader than the raw heading/body text alone.
        describe(
            title_label,
            name=f"Welcome to {APP_NAME}",
            description="This screen appears when no project is currently open.",
            focusable=False,
        )
        layout.addWidget(title_label)

        subtitle_label = QLabel(
            self.tr("Create a new project or open an existing one to get started.")
        )
        subtitle_label.setObjectName("welcomeSubtitle")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        describe(
            subtitle_label,
            name="Getting started",
            description="Create a new project or open an existing one to get started.",
            focusable=False,
        )
        layout.addWidget(subtitle_label)

        layout.addSpacing(16)

        self.button_new_project = QPushButton("New Project")
        self.button_new_project.setMinimumWidth(200)
        # Unit 5: both buttons already get a bare accessible name for free from their own
        # text() (same Qt fallback _uia_target_app.py's own docstring documents for button-
        # like widgets), so describe() here is about the *description* a screen reader
        # reads on top of that name, and the tooltip a sighted user hovering gets -- neither
        # existed before.
        describe(
            self.button_new_project,
            name="New Project",
            description="Start a new, empty project with no dataset loaded yet.",
            help_anchor="index",
        )
        layout.addWidget(
            self.button_new_project, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.button_open_project = QPushButton("Open Project...")
        self.button_open_project.setObjectName("secondaryButton")
        self.button_open_project.setMinimumWidth(200)
        describe(
            self.button_open_project,
            name="Open Project...",
            description="Open a previously saved project from disk.",
            help_anchor="index",
        )
        layout.addWidget(
            self.button_open_project, alignment=Qt.AlignmentFlag.AlignCenter
        )

        _logger.debug("Welcome widget constructed.")
