# File: src/ui/controllers/guidance_controller.py
"""Owns milestone 26's guidance wiring: ranked suggestions and expertise-driven density.

Like every other milestone-19-onward controller, this one holds only the collaborators it
actually needs and is constructed once in ``MainWindow._build_controllers`` -- split out of
``main_window.py`` itself (rather than left inline, the way this milestone's first pass wrote
it) once that file crossed ``tests.ui.test_module_size``'s 400-line budget, the same "one more
handler" growth that module's own docstring already warns about and that motivated
milestone 19's original controller extraction.

Two responsibilities, both genuinely about :class:`~src.core.expertise_level.ExpertiseLevel`
and neither large enough to deserve its own controller:

1. Recomputing :class:`~src.services.guidance_service.GuidanceService`'s ranked suggestions on
   every workbench refresh and pushing the same list into every
   :class:`~src.ui.workbench.stage_page.StagePage`'s ``GuidancePanel`` (see
   :meth:`refresh_suggestions`), plus turning an activated suggestion's plain ``action_id``
   string back into a real, invokable ``QAction`` via
   :class:`~src.ui.actions.action_binder.ActionBinder` (see :meth:`on_suggestion_activated`) --
   the same "structure in the widget, behavior wired by the caller" split every other
   workbench signal in this codebase already uses.
2. Driving :meth:`~src.ui.theme_manager.ThemeManager.set_density` from whichever expertise
   level is currently selected (see :meth:`set_theme_manager`/
   :meth:`on_expertise_combo_changed_for_density`) -- ``set_density`` has existed, unused,
   since milestone 15; this is the first real caller.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from src.core.expertise_level import ExpertiseLevel
from src.services.analysis_orchestrator_service import PipelineStage
from src.services.guidance_service import GuidanceService
from src.services.settings_service import SettingsService
from src.services.workspace_service import Dataset
from src.ui.actions.action_binder import ActionBinder
from src.ui.dock_manager import DockManager
from src.ui.theme.tokens import DENSITY_BY_EXPERTISE_LEVEL, Density
from src.ui.workbench.workbench import Workbench

if TYPE_CHECKING:
    from src.ui.theme_manager import ThemeManager

# How many of GuidanceService's ranked suggestions each GuidancePanel shows -- matches every
# other "small, session-scoped list" cap in this codebase (e.g. chart_recommender.
# recommend_charts's own default max_suggestions=5); a longer list would crowd the guidance
# card zone StagePage's own three-zone layout deliberately keeps compact.
_MAX_SUGGESTIONS_SHOWN = 5


class GuidanceController:
    """Recomputes ranked suggestions and drives theme density from the active expertise level.

    Args:
        guidance_service: Produces the ranked suggestion list.
        settings_service: Where ``ai.expertise_level`` is read from -- the same setting the
            chat panel's own expertise combo already drives (see
            :class:`~src.ui.controllers.assistant_controller.AssistantController`), so this
            controller adds no second, independent expertise-level control.
        workbench: Iterated (via :meth:`~src.ui.workbench.workbench.Workbench.all_pages`) to
            push suggestions into every page, and used to navigate
            (:meth:`~src.ui.workbench.workbench.Workbench.show_stage`) when a
            ``"workbench.go_to_<stage>"`` suggestion is activated.
        dock_manager: Its ``chat_panel.expertise_combo`` is what
            :meth:`on_expertise_combo_changed_for_density` reads from.
        binder: Resolves an activated suggestion's ``action_id`` to a real ``QAction`` and
            triggers it.
    """

    def __init__(
        self,
        guidance_service: GuidanceService,
        settings_service: SettingsService,
        workbench: Workbench,
        dock_manager: DockManager,
        binder: ActionBinder,
    ) -> None:
        self._guidance_service = guidance_service
        self._settings_service = settings_service
        self._workbench = workbench
        self._dock_manager = dock_manager
        self._binder = binder
        # Set by set_theme_manager -- constructed after this controller, by
        # src/core/app.py, the same reason MainWindow's own theme manager
        # reference is attached post-construction (see MainWindow.
        # attach_theme_manager's docstring).
        self._theme_manager: ThemeManager | None = None

        # Milestone 26: this controller wires its own signals here, in __init__, rather
        # than exposing a separate wire()/connect_actions() call site the way every other
        # controller defers to MainWindow._connect_actions -- every collaborator these
        # connections need (binder, workbench's pages, dock_manager's chat_panel) is
        # already fully constructed by the time MainWindow._build_controllers instantiates
        # this class (see that method's own docstring on construction order), so there is
        # no ordering hazard to defer for, and folding it in here is what let
        # main_window.py's own net line growth for this milestone stay small enough to
        # keep the whole file under tests.ui.test_module_size's 400-line budget.
        for stage in PipelineStage:
            if stage is PipelineStage.UPLOAD:
                continue  # no page/action for UPLOAD -- see builtin_actions.py's own comment
            binder.bind(
                f"workbench.go_to_{stage.value}", self._make_navigate_handler(stage)
            )
        dock_manager.chat_panel.expertise_combo.currentIndexChanged.connect(
            self.on_expertise_combo_changed_for_density
        )
        for page in workbench.all_pages():
            page.guidance_panel.suggestion_activated.connect(
                self.on_suggestion_activated
            )

    # -- Suggestions --------------------------------------------------------

    def on_suggestion_activated(self, action_id: str) -> None:
        """Trigger the real, shared ``QAction`` for a ``GuidancePanel`` suggestion.

        Milestone 26's own acceptance criterion -- every ``Suggestion.action_id``
        :class:`~src.services.guidance_service.GuidanceService` can ever produce resolves in
        :mod:`~src.ui.actions.action_registry` -- is what makes ``action_for(action_id)``
        below safe to call unconditionally: an unknown id would raise
        :class:`~src.core.exceptions.ServiceError`, the correct "this should never happen"
        failure mode here, not a silently swallowed no-op.
        """
        self._binder.action_for(action_id).trigger()

    def refresh_suggestions(self, active_dataset: Dataset | None) -> None:
        """Recompute ranked suggestions and push the same list into every stage page.

        Called from ``MainWindow._refresh_workbench`` alongside every other "recompute from
        live state and push into the (otherwise service-free) workbench" call already made
        there. Every page gets the same list -- unlike the proposal-only ``set_guidance`` call
        :class:`~src.ui.workbench.workbench.Workbench.update_pipeline_state` makes to only the
        currently-*proposed* stage's page -- because a suggestion (a chart recommendation, a
        data-quality finding) is genuinely useful regardless of which stage page a user
        happens to be looking at right now.
        """
        expertise_level = ExpertiseLevel(
            self._settings_service.get("ai", "expertise_level", default="beginner")
        )
        suggestions = self._guidance_service.get_suggestions(
            active_dataset, expertise_level, max_suggestions=_MAX_SUGGESTIONS_SHOWN
        )
        for page in self._workbench.all_pages():
            page.update_suggestions(suggestions)

    # -- Navigation (workbench.go_to_<stage> action handlers) --------------------------------

    def navigate_to_stage(self, stage: PipelineStage) -> None:
        """Switch the workbench to ``stage``'s page -- the handler every ``workbench.go_to_*``
        action is bound to. Delegates to :meth:`~src.ui.workbench.workbench.Workbench.
        show_stage`, the same real navigation :class:`~src.ui.workbench.stage_rail.StageRail`'s
        own item-click handler already uses, so a suggestion, the command palette, and clicking
        the rail directly all end up calling the exact same method.
        """
        self._workbench.show_stage(stage)

    def _make_navigate_handler(self, stage: PipelineStage) -> Callable[[], None]:
        """Return a zero-argument closure over ``stage`` for :meth:`navigate_to_stage`.

        A real method rather than an inline ``lambda`` in ``__init__``'s binding loop --
        this is what lets each closure capture its own ``stage`` by value (a plain
        ``lambda: self.navigate_to_stage(stage)`` inside a ``for`` loop would close over the
        loop variable itself, and every bound action would navigate to whichever stage the
        loop last visited -- the classic late-binding-closure bug, matching the same
        reasoning ``ApplicationMenuBar.update_recent_projects_menu``'s own comment gives for
        its `path=path_str` default-argument workaround). Using a real method's own default
        argument binding at call time (each call gets a fresh ``stage`` parameter) sidesteps
        that without needing a default-argument lambda, and gives mypy a real, inferrable
        return type besides.
        """
        return lambda: self.navigate_to_stage(stage)

    # -- Expertise-driven density (ThemeManager.set_density(), unused since milestone 15) ----

    def set_theme_manager(self, theme_manager: ThemeManager) -> None:
        """Attach the running application's ``ThemeManager`` and apply the current density.

        Called once by ``MainWindow.attach_theme_manager``, mirroring
        :meth:`~src.ui.dock_manager.DockManager.attach_theme_manager`'s own "attach after
        construction, since ThemeManager cannot exist before the QApplication does" pattern.
        Applies the density matching the currently configured expertise level immediately -- a
        session that starts at "engineer," say, should not have to toggle the expertise combo
        once just to get COMPACT density.
        """
        self._theme_manager = theme_manager
        self._apply_density_for_expertise_level(
            self._settings_service.get("ai", "expertise_level", default="beginner")
        )

    def on_expertise_combo_changed_for_density(self, index: int) -> None:
        """Slot for the chat panel's expertise combo's ``currentIndexChanged`` signal.

        Mirrors :meth:`~src.ui.controllers.assistant_controller.AssistantController.
        on_expertise_level_changed`'s own ``itemData`` read exactly, so both slots agree on
        what the combo's current selection means. A second slot on the same signal, not a
        change to ``AssistantController``, since density is a UI/theme concern with nothing to
        do with the running ``AssistantService``.
        """
        level = self._dock_manager.chat_panel.expertise_combo.itemData(index)
        if not level:
            return  # defensive: same empty/uninitialized-combo guard as the sibling slot
        self._apply_density_for_expertise_level(level)

    def _apply_density_for_expertise_level(self, level: str) -> None:
        if self._theme_manager is None:
            return  # not yet attached -- see set_theme_manager's own docstring
        density = DENSITY_BY_EXPERTISE_LEVEL.get(ExpertiseLevel(level), Density.COZY)
        self._theme_manager.set_density(density)
