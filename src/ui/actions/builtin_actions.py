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

``edit.undo``/``edit.redo`` are deliberately **not registered here**. Before
this milestone they were real, clickable ``QAction``s connected to nothing
-- exactly the dead-action defect this whole package exists to make
impossible. Milestone 23 is where real undo/redo semantics land; until
then, removing the actions entirely is more honest than keeping a
permanently-disabled placeholder, matching this plan's own reasoning for
removing the Project Explorer dock in milestone 20 rather than leaving it
permanently showing "(No project open)".
"""

from __future__ import annotations

from src.ui.actions.action_registry import (
    ActionCategory,
    ActionSpec,
    Requirement,
    register_action,
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
            action_id="help.about",
            label="&About",
            category=ActionCategory.HELP,
            icon_name="circle-help",
            status_tip="About this application",
            help_anchor="index",
        )
    )


_register_builtins()
