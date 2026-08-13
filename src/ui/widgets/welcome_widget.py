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
        layout.addWidget(title_label)

        subtitle_label = QLabel("Create a new project or open an existing one to get started.")
        subtitle_label.setObjectName("welcomeSubtitle")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)

        layout.addSpacing(16)

        self.button_new_project = QPushButton("New Project")
        self.button_new_project.setMinimumWidth(200)
        layout.addWidget(self.button_new_project, alignment=Qt.AlignmentFlag.AlignCenter)

        self.button_open_project = QPushButton("Open Project...")
        self.button_open_project.setObjectName("secondaryButton")
        self.button_open_project.setMinimumWidth(200)
        layout.addWidget(self.button_open_project, alignment=Qt.AlignmentFlag.AlignCenter)

        _logger.debug("Welcome widget constructed.")
