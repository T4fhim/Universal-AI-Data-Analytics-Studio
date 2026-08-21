# File: src/ui/actions/builtin_actions.py
"""Registers every action built before milestone 17.

Populated once at import time (bottom of this module), the same convention
:func:`~src.visualization.chart_registry._register_builtins` already
established -- both ``main_window.py`` (via ``menu_bar.py``/``toolbar.py``)
and ``tests/ui/actions/`` import this module, so import-time population
guarantees the registry is full before either first reads from it, with no
separate "initialize the actions" call any entry point would need to
remember to make.

Each ``requires``/``predicate`` here was read directly off the *current*
handler bodies in ``main_window.py`` before this milestone -- not assumed --
so enablement introduces no new precondition a user could not already hit
by clicking the always-enabled action and reading the resulting message
box. For example ``analysis.generate_report`` requires an active dataset
(not an open project, which would have been the more "obvious" guess):
``_on_generate_report`` reads ``self._workspace_service.get_active_dataset()``
and shows "No Active Dataset" if it is ``None``, never touching
``ProjectService`` at all.

``edit.undo``/``edit.redo`` **are now registered** (milestone 23) -- see
:mod:`~src.ui.command_stack`'s own docstring for the real semantics behind
them. Both use ``predicate`` rather than ``requires``: ``Requirement`` has no
"can undo" member (a boolean precondition would be the wrong shape even if
it did -- see ``ActionContext.can_undo``'s own docstring on why it is a
plain field, not derived from a ``Requirement``), so each reads
``ActionContext.can_undo``/``can_redo`` directly, the same way
``analysis.dashboard`` already reads ``visualization_count`` via its own
predicate rather than forcing a boolean ``Requirement`` to fit.
"""

from __future__ import annotations

from src.services.analysis_orchestrator_service import PipelineStage
from src.ui.actions.action_registry import (
    ActionCategory,
    ActionSpec,
    Requirement,
    register_action,
)

# Milestone 26: one "jump to this stage" action per PipelineStage that has a
# real registered workbench page (src.ui.workbench.stage_registry) -- UPLOAD
# is excluded, matching Workbench._on_stage_selected's own silent-no-op
# handling of it (there is no page to jump to; the welcome page represents
# it instead). (label, icon_name) per stage -- icon names are real files
# under resources/icons/ (asserted by tests.ui.actions.test_builtin_actions.
# test_every_icon_name_exists_on_disk).
_STAGE_NAV_ACTIONS: tuple[tuple[PipelineStage, str, str], ...] = (
    (PipelineStage.UNDERSTAND, "Go to &Understand Stage", "eye"),
    (PipelineStage.CLEAN, "Go to &Clean Stage", "brush-cleaning"),
    (PipelineStage.EXPLORE, "Go to E&xplore Stage", "search"),
    (PipelineStage.ANALYZE, "Go to &Analyze Stage", "sliders"),
    (PipelineStage.VISUALIZE, "Go to &Visualize Stage", "chart-bar"),
    (PipelineStage.PREDICT, "Go to &Predict Stage", "trending-up"),
    (PipelineStage.EXPLAIN, "Go to E&xplain Stage", "sparkles"),
    (PipelineStage.REPORT, "Go to &Report Stage", "file-text"),
    (PipelineStage.REPRODUCE, "Go to Re&produce Stage", "refresh"),
)


def _register_builtins() -> None:
    register_action(
        ActionSpec(
            action_id="project.new",
            label="&New Project",
            category=ActionCategory.PROJECT,
            icon_name="file-plus",
            shortcut="Ctrl+N",
            status_tip="Create a new, empty project",
            help_anchor="project/new",
        )
    )
    register_action(
        ActionSpec(
            action_id="project.open",
            label="&Open Project...",
            category=ActionCategory.PROJECT,
            icon_name="folder-open",
            shortcut="Ctrl+O",
            status_tip="Open an existing project file",
            help_anchor="project/open",
        )
    )
    register_action(
        ActionSpec(
            action_id="dataset.open",
            label="Open &Dataset...",
            category=ActionCategory.DATASET,
            icon_name="table",
            # Ctrl+O is already claimed by project.open above -- this
            # needs its own, non-conflicting shortcut, matching the
            # pre-milestone-17 menu_bar.py comment this carries forward.
            shortcut="Ctrl+Shift+O",
            status_tip="Load a data file into the workspace",
            help_anchor="data/open-dataset",
        )
    )
    register_action(
        ActionSpec(
            action_id="dataset.connect_database",
            label="Connect to &Database...",
            category=ActionCategory.DATASET,
            icon_name="database",
            status_tip="Connect to a live database and import a table",
            help_anchor="data/connect-database",
        )
    )
    register_action(
        ActionSpec(
            action_id="project.save",
            label="&Save Project",
            category=ActionCategory.PROJECT,
            icon_name="save",
            shortcut="Ctrl+S",
            status_tip="Save the active project",
            requires=frozenset({Requirement.PROJECT_OPEN}),
            help_anchor="project/save",
        )
    )
    register_action(
        ActionSpec(
            action_id="project.save_as",
            label="Save Project &As...",
            category=ActionCategory.PROJECT,
            shortcut="Ctrl+Shift+S",
            status_tip="Save the active project to a new file",
            requires=frozenset({Requirement.PROJECT_OPEN}),
            help_anchor="project/save-as",
        )
    )
    register_action(
        ActionSpec(
            action_id="project.settings",
            label="Se&ttings...",
            category=ActionCategory.PROJECT,
            icon_name="settings",
            shortcut="Ctrl+,",
            status_tip="Open application settings",
            help_anchor="settings",
        )
    )
    register_action(
        ActionSpec(
            action_id="project.exit",
            label="E&xit",
            category=ActionCategory.PROJECT,
            icon_name="x",
            shortcut="Ctrl+Q",
            status_tip="Exit the application",
            # A fuzzy-search palette mis-click quitting the whole
            # application is a disproportionate risk a menu click (which
            # requires deliberately navigating to File > Exit) does not
            # carry -- excluded from the palette rather than adding a
            # confirmation dialog the menu path has never needed either.
            palette_visible=False,
            help_anchor="project/exit",
        )
    )
    register_action(
        ActionSpec(
            action_id="view.toggle_theme",
            label="Toggle &Dark / Light Theme",
            category=ActionCategory.VIEW,
            icon_name="sun",
            status_tip="Switch between dark and light themes",
            help_anchor="view/theme",
        )
    )
    register_action(
        ActionSpec(
            action_id="analysis.visualize",
            label="&Visualize...",
            category=ActionCategory.ANALYSIS,
            icon_name="chart-bar",
            status_tip="Create a chart from the active dataset",
            requires=frozenset({Requirement.ACTIVE_DATASET}),
            help_anchor="visualize/create-chart",
        )
    )
    register_action(
        ActionSpec(
            action_id="analysis.dashboard",
            label="Create &Dashboard",
            category=ActionCategory.ANALYSIS,
            icon_name="layout-dashboard",
            status_tip="Combine open visualizations into a dashboard",
            # _on_create_dashboard's real precondition is "at least two"
            # visualizations, which Requirement (boolean-only) cannot
            # express -- a predicate reading the count instead.
            predicate=lambda ctx: ctx.visualization_count >= 2,
            help_anchor="visualize/dashboard",
        )
    )
    register_action(
        ActionSpec(
            action_id="analysis.generate_report",
            label="&Generate Report...",
            category=ActionCategory.ANALYSIS,
            icon_name="file-text",
            status_tip="Export the active dataset's analysis log as a report",
            requires=frozenset({Requirement.ACTIVE_DATASET}),
            help_anchor="report/generate",
        )
    )
    register_action(
        ActionSpec(
            action_id="edit.undo",
            label="&Undo",
            category=ActionCategory.EDIT,
            icon_name="undo",
            shortcut="Ctrl+Z",
            status_tip="Undo the most recent cleaning operation",
            predicate=lambda ctx: ctx.can_undo,
            help_anchor="edit/undo",
        )
    )
    register_action(
        ActionSpec(
            action_id="edit.redo",
            label="&Redo",
            category=ActionCategory.EDIT,
            icon_name="redo",
            shortcut="Ctrl+Y",
            status_tip="Redo the most recently undone cleaning operation",
            predicate=lambda ctx: ctx.can_redo,
            help_anchor="edit/redo",
        )
    )
    register_action(
        ActionSpec(
            action_id="help.about",
            label="&About",
            category=ActionCategory.HELP,
            icon_name="circle-help",
            status_tip="About this application",
            help_anchor="index",
        )
    )

    # Milestone 26: stage-navigation actions -- see _STAGE_NAV_ACTIONS above.
    # Each requires an active dataset (matching StagePage's own reason for
    # existing -- there is nothing to show a stage page for otherwise) and
    # carries `stage` so GuidanceService.get_suggestions can map a
    # PIPELINE-source Suggestion straight onto a real, resolvable action id
    # (`f"workbench.go_to_{stage.value}"`) without importing anything from
    # src.ui itself.
    for stage, label, icon_name in _STAGE_NAV_ACTIONS:
        register_action(
            ActionSpec(
                action_id=f"workbench.go_to_{stage.value}",
                label=label,
                category=ActionCategory.PIPELINE,
                icon_name=icon_name,
                status_tip=f"Jump to the {stage.value.title()} stage",
                requires=frozenset({Requirement.ACTIVE_DATASET}),
                # Matches each StagePage subclass's own help_anchor
                # ("pipeline.<stage>") exactly -- see e.g.
                # src/ui/workbench/pages/understand_page.py -- so F1 from
                # either this action or the page it jumps to opens the same
                # manual section (both are M29 scope; unvalidated today).
                help_anchor=f"pipeline.{stage.value}",
                stage=stage,
            )
        )


_register_builtins()
