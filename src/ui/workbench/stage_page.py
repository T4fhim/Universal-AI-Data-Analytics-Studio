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
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from src.services.analysis_orchestrator_service import PipelineStage
from src.services.guidance_service import Suggestion
from src.ui.a11y.accessible import HELP_ANCHOR_PROPERTY, describe
from src.ui.widgets.error_state import ErrorState
from src.ui.widgets.guidance_panel import GuidancePanel


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
        # Milestone 29: stamped on the page container itself, not only on individual
        # described widgets (every concrete subclass's own run/generate/reproduce button
        # already carries this -- see e.g. UnderstandPage._build_form). ExplainPage has no
        # interactive control at all to stamp, and any subclass's non-button widgets (combo
        # boxes, labels) are never described with help_anchor -- without this, F1 pressed
        # while focus sits on one of those would climb the parent chain past this page
        # entirely and find nothing. Stamping the container guarantees resolve_help_anchor
        # succeeds for focus anywhere inside a stage page, not only on its one described button.
        self.setProperty(HELP_ANCHOR_PROPERTY, self.help_anchor)

        # Unit-4-regression fix: a stage page's total content height has no ceiling --
        # VisualizePage alone stacks two QGroupBoxes, a dynamic per-chart-type field form,
        # and a chart+table split, and different chart types/dataset shapes can make any
        # page's content taller than whatever window/dock space it is actually given. Before
        # this, the three zones below were laid directly into this page's own QVBoxLayout
        # with nothing to fall back on when total height exceeded the available viewport --
        # Qt's layout system does not clip or add scrollbars on its own; it silently renders
        # child widgets (observed: VisualizePage's per-field QFormLayout rows) squeezed below
        # their natural height, which reads as overlapping text, not a clean cutoff. A
        # QScrollArea around the real content, with setWidgetResizable(True) so the inner
        # widget's *width* always tracks the scroll area's (only height ever scrolls), is the
        # standard Qt fix: content that already fits renders exactly as before -- no visible
        # scrollbar -- content that doesn't scrolls instead of corrupting.
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea(self)
        scroll_area.setObjectName("stagePageScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        outer_layout.addWidget(scroll_area)

        # The three zones below are built into this content widget, not `self` directly --
        # `self` now holds only the scroll area (see outer_layout above).
        content = QWidget(scroll_area)
        content.setObjectName("stagePageScrollContent")
        scroll_area.setWidget(content)
        layout = QVBoxLayout(content)

        # Zone 1: guidance card + suggestion panel, grouped in one QFrame (UI-friendliness
        # pass, unit 4) so the two read as a single "why this stage / what to try" zone
        # instead of two independent labels floating at the top of the page -- previously
        # both were direct children of this page's own layout with nothing visually tying
        # them together or separating them from Zone 2's form. stagePageZone_guidance is
        # purely a styling hook (see base.qss.template); it owns no behavior of its own.
        guidance_zone = QFrame(content)
        guidance_zone.setObjectName("stagePageZone_guidance")
        guidance_zone_layout = QVBoxLayout(guidance_zone)
        guidance_zone_layout.setContentsMargins(0, 0, 0, 0)

        # Static at construction (each subclass may seed its own default text),
        # overwritten by Workbench.update_pipeline_state with the live
        # StageProposal.rationale whenever this page's stage is the one currently proposed.
        self._guidance_label = QLabel(guidance_zone)
        self._guidance_label.setObjectName("stageGuidanceCard")
        self._guidance_label.setWordWrap(True)
        describe(
            self._guidance_label,
            name=f"{self.stage.value.title()} stage guidance",
            description="Explains why this stage is recommended next.",
            focusable=False,  # a label with text, not a control to tab to
        )
        guidance_zone_layout.addWidget(self._guidance_label)

        # Milestone 26: one GuidancePanel per stage page, in the guidance-card zone
        # alongside the static rationale label above -- see GuidancePanel's own docstring
        # for why this lives here rather than as a single shared dock. Populated by
        # update_suggestions below; starts empty (its own "No suggestions right now."
        # placeholder) until the first real MainWindow._refresh_workbench call pushes a
        # ranked list in.
        self.guidance_panel = GuidancePanel(guidance_zone)
        guidance_zone_layout.addWidget(self.guidance_panel)

        layout.addWidget(guidance_zone)

        # Zone 3's widget is constructed here, ahead of Zone 2's form, but
        # not yet added to the layout -- a subclass's _build_form (called
        # below) is allowed to call set_result_text/set_guidance to seed an
        # initial default (see ReportPage/ReproducePage), so the label it
        # writes to must already exist before that call runs. Layout order
        # (guidance, form, result) is still established explicitly by the
        # addWidget calls below, independent of construction order.
        self._result_label = QLabel(content)
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

        # Milestone 27: a persistent, in-page ErrorState -- see this class's own module
        # docstring reference and src/ui/widgets/error_state.py's own docstring for why a
        # stage-page tool-call failure gets an in-page home rather than a QMessageBox.critical
        # dialog. Hidden until show_error() is called; constructed here (Zone 3, alongside
        # _result_label) so every StagePage subclass gets it for free rather than each page
        # wiring its own.
        self._error_state = ErrorState(
            heading=f"{self.stage.value.title()} stage error",
            message="",
            parent=content,
        )
        self._error_state.setVisible(False)

        # Zone 2: the parameter form, supplied entirely by the subclass. objectName is a
        # pure styling hook (unit 4) -- QWidget rather than QFrame since it was already a
        # bare container pre-unit-4 and every subclass's _build_form already populates
        # self._form_layout directly; no structural change needed here, unlike zones 1/3.
        self._form_container = QWidget(content)
        self._form_container.setObjectName("stagePageZone_form")
        self._form_layout = QVBoxLayout(self._form_container)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._form_container)
        self._build_form(self._form_layout)

        # Zone 3: result label + error state, grouped in one frame for the same reason
        # Zone 1's guidance_zone groups its two widgets -- see that comment above.
        result_zone = QFrame(content)
        result_zone.setObjectName("stagePageZone_result")
        result_zone_layout = QVBoxLayout(result_zone)
        result_zone_layout.setContentsMargins(0, 0, 0, 0)
        result_zone_layout.addWidget(self._result_label)
        result_zone_layout.addWidget(self._error_state)
        layout.addWidget(result_zone)

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

    def show_error(self, heading: str, message: str) -> None:
        """Show a persistent, in-page :class:`~src.ui.widgets.error_state.ErrorState`.

        Replaces the ``QMessageBox.critical(self, heading, message)`` calls every stage page's
        tool-call exception handler used before milestone 27 -- see
        :mod:`~src.ui.widgets.error_state`'s own docstring for why a stage-page failure (the
        page itself stays visible and reusable afterward) is a persistent in-page state rather
        than a one-shot modal interruption.
        """
        self._error_state.set_error(heading, message)
        self._error_state.setVisible(True)

    def clear_error(self) -> None:
        """Hide the error state -- called at the start of a fresh run, before it can fail again."""
        self._error_state.setVisible(False)

    def update_suggestions(self, suggestions: list[Suggestion]) -> None:
        """Push a freshly ranked suggestion list into this page's :attr:`guidance_panel`.

        Called by :mod:`src.ui.main_window` (via :meth:`~src.ui.workbench.workbench.
        Workbench.all_pages`) with the same ranked list on every page -- unlike
        :meth:`set_guidance`, which only the *proposed* stage's page receives (see
        :meth:`~src.ui.workbench.workbench.Workbench.update_pipeline_state`), suggestions are
        genuinely useful regardless of which stage a user is currently looking at (a chart
        suggestion is relevant even while reading the Clean stage's page).
        """
        self.guidance_panel.set_suggestions(suggestions)
