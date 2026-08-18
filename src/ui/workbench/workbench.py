# File: src/ui/workbench/workbench.py
"""The application's central widget from milestone 20 onward: rail + stacked stage pages.

Replaces ``MainWindow``'s one-and-only ``setCentralWidget(WelcomeWidget)`` call. Unlike
``WelcomeWidget``, which occupied the central widget forever, :class:`Workbench` is the
permanent central widget itself -- it starts on :attr:`welcome_page` and switches its internal
``QStackedWidget`` to a stage page once a dataset is active (see :meth:`update_pipeline_state`),
rather than the welcome content simply staying visible underneath everything for the rest of
the session (the exact defect the plan's Context section names as its own top complaint).

Holds no service references (see this package's ``__init__`` docstring): every method here
takes plain, already-computed data and either renders it or emits a signal. The one exception
worth naming is that :meth:`update_pipeline_state` imports nothing new to do this -- it works
entirely off :class:`~src.services.analysis_orchestrator_service.AnalysisLog`/``StageProposal``,
both plain dataclasses with no Qt or service-instance dependency of their own.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QWidget

from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import (
    AnalysisLog,
    PipelineStage,
    StageProposal,
)
from src.ui.workbench.pages.welcome_page import WelcomePage
from src.ui.workbench.stage_page import StagePage
from src.ui.workbench.stage_rail import StageRail
from src.ui.workbench.stage_registry import get_stage_page_class, list_registered_stages

_logger = get_logger(__name__)


class Workbench(QWidget):
    """``StageRail`` + a ``QStackedWidget`` of the welcome page and every registered stage page."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workbench")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stage_rail = StageRail(self)
        layout.addWidget(self.stage_rail)

        self.stack = QStackedWidget(self)
        layout.addWidget(self.stack, 1)

        self.welcome_page = WelcomePage(self)
        self.stack.addWidget(self.welcome_page)

        # One page instance per registered stage, built once at construction --
        # matching how DockManager builds every dock up front rather than
        # lazily on first visit, since a stage page's own construction cost
        # (a handful of labels and a button) is negligible next to the Qt
        # widget-tree churn lazy construction would add on every stage switch.
        self._pages: dict[PipelineStage, StagePage] = {}
        for stage in list_registered_stages():
            page_class = get_stage_page_class(stage)
            assert page_class is not None  # list_registered_stages guarantees this
            page = page_class(self)
            self._pages[stage] = page
            self.stack.addWidget(page)

        self.stack.setCurrentWidget(self.welcome_page)
        self.stage_rail.stage_selected.connect(self._on_stage_selected)

        _logger.debug("Workbench constructed with %d stage page(s).", len(self._pages))

    def page_for(self, stage: PipelineStage) -> StagePage | None:
        """Return the constructed page for ``stage``, or ``None`` if it has no page yet."""
        return self._pages.get(stage)

    def _on_stage_selected(self, stage: PipelineStage) -> None:
        page = self._pages.get(stage)
        if page is not None:
            self.stack.setCurrentWidget(page)
        # A rail click on a stage with no page yet (CLEAN/EXPLORE/ANALYZE/
        # VISUALIZE/PREDICT/EXPLAIN -- milestones 23-26) is a silent no-op
        # rather than an error dialog: the rail still shows the stage's real
        # status for orientation, it just isn't clickable-through yet, the
        # same "reachable but not yet interactive" state a disabled menu
        # action would represent, without needing a QAction-shaped mechanism
        # here just to express it.

    def show_welcome(self) -> None:
        """Switch to the welcome page -- called when no dataset is active."""
        self.stack.setCurrentWidget(self.welcome_page)

    def show_stage(self, stage: PipelineStage) -> None:
        """Switch to ``stage``'s page, if one is registered. No-op otherwise."""
        page = self._pages.get(stage)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def update_pipeline_state(
        self,
        *,
        dataset_active: bool,
        log: AnalysisLog | None,
        proposal: StageProposal | None,
    ) -> None:
        """Refresh the rail and every stage page from real orchestrator state.

        Args:
            dataset_active: Whether a dataset is currently active. When ``True``,
                ``PipelineStage.UPLOAD`` is shown complete on the rail -- UPLOAD is never
                itself run through
                :meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.run_stage`
                (see that module's ``_AUTO_PROPOSED_STAGES`` comment), so "a dataset exists"
                is the only signal this method has for it. When ``False``, the workbench
                switches to the welcome page -- this is the "opening a dataset transitions
                the center pane" behavior; closing the active dataset (there is currently no
                UI action that does this) would transition back.
            log: The active dataset's
                :class:`~src.services.analysis_orchestrator_service.AnalysisLog`, or ``None``
                if no dataset is active.
            proposal: The current
                :class:`~src.services.analysis_orchestrator_service.StageProposal`, or
                ``None`` if no dataset is active.
        """
        completed = set(log.completed_stages()) if log is not None else set()
        if dataset_active:
            completed.add(PipelineStage.UPLOAD)
        proposed_stage = proposal.stage if proposal is not None else None
        self.stage_rail.update_state(completed, proposed_stage)

        if proposal is not None:
            proposed_page = self._pages.get(proposal.stage)
            if proposed_page is not None:
                proposed_page.set_guidance(proposal.rationale)

        for page in self._pages.values():
            update_log = getattr(page, "update_log", None)
            if callable(update_log):
                update_log(log)

        if not dataset_active:
            self.show_welcome()
        elif (
            self.stack.currentWidget() is self.welcome_page
            and proposal is not None
            and proposal.stage in self._pages
        ):
            # Auto-navigate away from the welcome page the moment a dataset
            # becomes active, matching "opening a dataset transitions the
            # center pane" -- but only from the welcome page. Once the user
            # has manually navigated the rail themselves, later calls to this
            # method (a stage just finished running, an unrelated state-bus
            # refresh) must not yank them back to whatever is newly proposed
            # -- that would contradict the plan's own "free-roam escape
            # hatch so experts are never forced through stages" decision.
            self.show_stage(proposal.stage)
