# File: src/ui/dialogs/about_dialog.py
"""The application's About dialog.

Simplest dialog in this milestone: static informational text and a
single close button, with no service dependencies at all. Built before
:mod:`settings_dialog` specifically to establish the basic
``QDialog`` construction pattern (title, layout, close behavior) once,
cleanly, before the more involved settings dialog needs to do the same
thing while also wiring to a real service.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.constants import APP_NAME, APP_VERSION, ORGANIZATION_NAME
from src.core.logger import get_logger

_logger = get_logger(__name__)


class AboutDialog(QDialog):
    """A modal dialog showing application name, version, and organization."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        name_label = QLabel(APP_NAME)
        name_label.setObjectName("welcomeTitle")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        version_label = QLabel(f"Version {APP_VERSION}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version_label)

        org_label = QLabel(ORGANIZATION_NAME)
        org_label.setObjectName("welcomeSubtitle")
        org_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(org_label)

        layout.addSpacing(16)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignCenter)

        _logger.debug("About dialog constructed.")
