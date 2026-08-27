# File: src/ui/workbench/pages/welcome_page.py
"""The workbench's default page: shown until a dataset is active.

Not a :class:`~src.ui.workbench.stage_page.StagePage` -- there is no
:class:`~src.services.analysis_orchestrator_service.PipelineStage` value for "nothing is open
yet" (``UPLOAD`` means a dataset already exists; see that enum's own docstring), so forcing this
page through the three-zone guidance/form/result shape would misrepresent it as stage content.

Wraps :class:`~src.ui.widgets.welcome_widget.WelcomeWidget` by composition rather than
reimplementing its title/subtitle/buttons here -- that widget's own content is still correct
for "no project is open," milestone 20 only changes *where* it lives (a workbench page instead
of the permanent central widget) and *how long* it stays visible (until a dataset becomes
active, not forever -- see :meth:`~src.ui.workbench.workbench.Workbench.update_pipeline_state`).
:attr:`button_new_project`/:attr:`button_open_project` are re-exposed unchanged so
``main_window.py``'s existing ``_connect_actions`` wiring needs only a one-line target change,
not a rewrite.
"""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.ui.widgets.welcome_widget import WelcomeWidget


class WelcomePage(QWidget):
    """Hosts :class:`~src.ui.widgets.welcome_widget.WelcomeWidget` as the workbench's initial page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workbenchWelcomePage")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.welcome_widget = WelcomeWidget(self)
        layout.addWidget(self.welcome_widget)

        self.button_new_project = self.welcome_widget.button_new_project
        self.button_open_project = self.welcome_widget.button_open_project
