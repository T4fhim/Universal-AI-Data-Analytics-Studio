# File: src/ui/workbench/__init__.py
"""The guided-pipeline workbench: the application's central widget from milestone 20 onward.

Before this milestone, :class:`~src.ui.widgets.welcome_widget.WelcomeWidget` was
``MainWindow``'s central widget forever -- ``setCentralWidget`` was called exactly
once, in ``MainWindow.__init__``, and never again (see this overhaul's own audit,
recorded in the plan document's Context section). :class:`~src.ui.workbench.workbench.Workbench`
replaces it: a persistent ``QHBoxLayout`` of :class:`~src.ui.workbench.stage_rail.StageRail`
(the pipeline's navigation spine) and a ``QStackedWidget`` holding one welcome page plus one
:class:`~src.ui.workbench.stage_page.StagePage` per registered
:class:`~src.services.analysis_orchestrator_service.PipelineStage`.

This package is display-only, matching :mod:`src.ui.dock_manager`'s own shape: it holds no
service references and calls nothing in :mod:`src.services` or :mod:`src.ui.controllers`
directly (see ``tests/ui/test_import_layering.py``'s ``_WIDGET_LIKE_PACKAGES``, which this
package joins in milestone 20). Business logic -- reading pipeline state, running a stage,
reproducing a log -- lives in :class:`~src.ui.controllers.pipeline_controller.PipelineController`;
this package only renders whatever snapshot it is handed and emits Qt signals when the user
asks for something to happen, the same "structure here, behavior wired by the caller" split
``main_window.py`` already uses for :class:`~src.ui.widgets.welcome_widget.WelcomeWidget`'s
own buttons.
"""

from __future__ import annotations
