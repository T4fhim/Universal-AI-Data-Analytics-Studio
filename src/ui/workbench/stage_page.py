# File: src/ui/workbench/stage_page.py
"""The three-zone page shape every pipeline stage's workbench content follows.

Per the plan's A3 ("Stage workbench"): guidance card / parameter form / result area, in that
fixed order, top to bottom. A concrete stage page supplies only the middle zone (via
:meth:`StagePage._build_form`) -- the guidance card and result area are owned by this base
class so every stage's page looks and behaves the same way, and so "this page wants a fourth
zone" reads as an abstraction problem to fix here, not a reason to special-case one page (the
plan states this explicitly: "If a page wants a fourth zone, that is a signal the abstraction
is wrong, not a reason to special-case").

Declaring ``stage``/``help_anchor`` as ``ClassVar`` (rather than instance attributes set in
``__init__``) lets :mod:`~src.ui.workbench.stage_registry` validate a page class's declared
stage against its registration *before* ever constructing one -- see that module's
``register_stage_page``.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from src.services.analysis_orchestrator_service import PipelineStage
from src.ui.a11y.accessible import describe


class StagePage(QWidget):
    """Base class for one pipeline stage's workbench content.

    Class attributes:
        stage: Which :class:`~src.services.analysis_orchestrator_service.PipelineStage`
            this page represents. A concrete subclass must set this.
        help_anchor: The manual anchor F1 should open when this page has focus -- read by
            :func:`~src.ui.a11y.accessible.describe` via the ``helpAnchor`` dynamic property
            it stamps on every described widget (see that module's own docstring).
    """

    stage: ClassVar[PipelineStage]
    help_anchor: ClassVar[str]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(f"stagePage_{self.stage.value}")

        layout = QVBoxLayout(self)

        # Zone 1: guidance card. Static at construction (each subclass may seed
        # its own default text), overwritten by Workbench.update_pipeline_state
        # with the live StageProposal.rationale whenever this page's stage is
        # the one currently proposed.
        self._guidance_label = QLabel(self)
        self._guidance_label.setObjectName("stageGuidanceCard")
        self._guidance_label.setWordWrap(True)
        describe(
            self._guidance_label,
            name=f"{self.stage.value.title()} stage guidance",
            description="Explains why this stage is recommended next.",
            focusable=False,  # a label with text, not a control to tab to
        )
        layout.addWidget(self._guidance_label)

        # Zone 3's widget is constructed here, ahead of Zone 2's form, but
        # not yet added to the layout -- a subclass's _build_form (called
        # below) is allowed to call set_result_text/set_guidance to seed an
        # initial default (see ReportPage/ReproducePage), so the label it
        # writes to must already exist before that call runs. Layout order
        # (guidance, form, result) is still established explicitly by the
        # addWidget calls below, independent of construction order.
        self._result_label = QLabel(self)
        self._result_label.setObjectName("stageResultArea")
        self._result_label.setWordWrap(True)
        self._result_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        describe(
            self._result_label,
            name=f"{self.stage.value.title()} stage result",
            description="Shows this stage's most recent result.",
        )

        # Zone 2: the parameter form, supplied entirely by the subclass.
        self._form_container = QWidget(self)
        self._form_layout = QVBoxLayout(self._form_container)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._form_container)
        self._build_form(self._form_layout)

        layout.addWidget(self._result_label)
        layout.addStretch(1)

    def _build_form(self, layout: QVBoxLayout) -> None:
        """Populate the middle (parameter form) zone. No-op by default.

        Subclasses override this rather than ``__init__`` so the guidance-card/
        result-area construction above always runs, in order, regardless of
        what a specific stage's form needs -- the same reason
        :class:`~src.ui.widgets.data_table.data_table_view.DataTableView`-style
        widgets in this codebase build their fixed chrome in the base and let
        subclasses fill in only the variable part.
        """
        return

    def set_guidance(self, text: str) -> None:
        """Replace the guidance card's text -- called with a static default at
        construction time by most subclasses, and overwritten with the live
        :class:`~src.services.analysis_orchestrator_service.StageProposal.rationale`
        by :class:`~src.ui.workbench.workbench.Workbench` whenever this stage is
        the one currently proposed.
        """
        self._guidance_label.setText(text)

    def set_result_text(self, text: str) -> None:
        """Replace the result area's text."""
        self._result_label.setText(text)
