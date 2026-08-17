# File: src/ui/actions/action_context.py
"""An immutable snapshot of "what can the user do right now."

:class:`ActionContext` is what
:meth:`~src.ui.actions.action_binder.ActionBinder.refresh_enablement` checks
every :class:`~src.ui.actions.action_registry.ActionSpec`'s ``requires``/
``predicate`` against. Captured fresh on every recompute (see
:mod:`src.ui.ui_state_bus` for when that happens) rather than incrementally
updated, since the source of truth is always the live services
(:class:`~src.services.project_service.ProjectService`,
:class:`~src.services.workspace_service.WorkspaceService`), and re-deriving
a handful of booleans/counts from them is cheap enough that incremental
tracking would only add a second place these could drift out of sync.

:meth:`capture`'s column-count computation is **O(columns), never O(rows)**:
it reads ``DataFrame.dtypes`` (one entry per column), not the data itself --
this runs on every enablement recompute, potentially several times per
user session, so an O(rows) cost here would make the whole "no polling,
just recompute on demand" design (this overhaul's stated goal) scale badly
on a large dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.services.analysis_orchestrator_service import PipelineStage
from src.services.project_service import ProjectService
from src.services.settings_service import SettingsService
from src.services.workspace_service import WorkspaceService
from src.ui.actions.action_registry import Requirement


@dataclass(frozen=True)
class ActionContext:
    """A point-in-time snapshot of workspace/project/AI state.

    Attributes:
        has_project: Whether a project is currently open.
        has_active_dataset: Whether a dataset is currently active.
        visualization_count: Number of tracked visualizations -- a count,
            not a boolean, since ``analysis.dashboard``'s real precondition
            is "at least two" (see ``_on_create_dashboard`` in
            ``main_window.py``), which a boolean ``has_visualizations``
            could not express without also changing what "satisfied" means
            for every other action that might one day want "at least one."
        numeric_column_count: Numeric-dtype column count of the active
            dataset (0 if none is active).
        datetime_column_count: Datetime-dtype column count of the active
            dataset (0 if none is active).
        completed_stages: Pipeline stages the active dataset has completed,
            per :class:`~src.services.analysis_orchestrator_service.
            AnalysisOrchestratorService`. Read by milestone 26's
            ``GuidanceService`` re-ranking, unused by any predicate yet.
        ai_configured: Whether at least one AI provider is configured in
            settings -- cheap to check (a config read, not a live
            connection attempt), unlike actually constructing an
            ``AssistantService``.
        is_busy: Whether a background worker is currently running.
        can_undo: Always ``False`` until milestone 23 builds real undo
            semantics -- present now so predicates written today do not
            need touching again when it becomes meaningful. No
            ``ActionSpec`` reads it yet: ``edit.undo``/``edit.redo`` are
            deliberately not registered in milestone 17 (see
            ``builtin_actions.py``).
        can_redo: See ``can_undo``.
    """

    has_project: bool
    has_active_dataset: bool
    visualization_count: int
    numeric_column_count: int
    datetime_column_count: int
    completed_stages: frozenset[PipelineStage]
    ai_configured: bool
    is_busy: bool
    can_undo: bool
    can_redo: bool

    def satisfies(self, requirement: Requirement) -> bool:
        """Return whether this context satisfies a single named requirement."""
        if requirement is Requirement.PROJECT_OPEN:
            return self.has_project
        if requirement is Requirement.ACTIVE_DATASET:
            return self.has_active_dataset
        # Exhaustiveness guard: a new Requirement member with no branch
        # here must fail loudly (a silently-always-disabled or
        # silently-always-enabled action is a worse failure mode than a
        # crash during development).
        raise AssertionError(f"Unhandled Requirement: {requirement!r}")

    @classmethod
    def capture(
        cls,
        *,
        project_service: ProjectService,
        workspace_service: WorkspaceService,
        settings_service: SettingsService,
        completed_stages: frozenset[PipelineStage] = frozenset(),
        is_busy: bool = False,
        can_undo: bool = False,
        can_redo: bool = False,
    ) -> ActionContext:
        """Build a fresh snapshot from the live services.

        Args:
            project_service: Queried for the active project.
            workspace_service: Queried for the active dataset and
                visualization count.
            settings_service: Queried for AI provider configuration.
            completed_stages: Passed through -- computing this requires
                :class:`~src.services.analysis_orchestrator_service.
                AnalysisOrchestratorService`, which this method does not
                take a dependency on (no current action needs it; a caller
                that does, e.g. milestone 26's ``GuidanceService``
                integration, computes it and passes it in rather than this
                method growing a fourth service parameter for one field).
            is_busy: Passed through from whatever tracks worker activity
                (``MainWindow`` in milestone 17 -- see its
                ``_busy_worker_count``).
            can_undo: Passed through; always ``False`` until milestone 23.
            can_redo: Passed through; always ``False`` until milestone 23.
        """
        active_dataset = workspace_service.get_active_dataset()
        if active_dataset is not None:
            dtypes = active_dataset.dataframe.dtypes
            numeric_column_count = sum(1 for dt in dtypes if dt.kind in "iuf")
            datetime_column_count = sum(1 for dt in dtypes if dt.kind == "M")
        else:
            numeric_column_count = 0
            datetime_column_count = 0

        return cls(
            has_project=project_service.get_active_project() is not None,
            has_active_dataset=active_dataset is not None,
            visualization_count=len(workspace_service.list_visualizations()),
            numeric_column_count=numeric_column_count,
            datetime_column_count=datetime_column_count,
            completed_stages=completed_stages,
            ai_configured=bool(settings_service.get("ai", "providers", default=[])),
            is_busy=is_busy,
            can_undo=can_undo,
            can_redo=can_redo,
        )
