# File: src/ui/controllers/__init__.py
"""Per-concern owners of the handler logic ``main_window.py`` used to hold directly.

Before milestone 19, every menu/toolbar action's handler was a
``MainWindow`` method -- 942 lines of project/dataset/visualization/report/
assistant logic all living in one class, growing by "one more handler" with
every milestone (:mod:`tests.ui.test_module_size`'s own docstring names this
exact failure mode). This package splits that by concern, one controller
per area, each constructed once in ``MainWindow.__init__`` and holding
whatever services/UI collaborators (``dock_manager``, ``status_bar``,
:class:`~src.ui.ui_state_bus.UiStateBus`,
:class:`~src.ui.worker_runner.WorkerRunner`) it actually needs -- not a
shared "god context" object, since each controller's own dependency list is
already documented by its constructor signature.

This is a pure refactor milestone: every controller method here is the same
logic that used to live on ``MainWindow``, moved verbatim (docstrings,
comments, and reasoning intact) rather than redesigned. ``MainWindow``
itself becomes the composition root that constructs these controllers and
wires :class:`~src.ui.actions.action_binder.ActionBinder` to their methods,
plus whatever remains genuinely window-level (the settings dialog, theme
attachment, the about dialog, window lifecycle).

Controllers are not a foundation/leaf layer the way ``theme``/``a11y``/
``actions`` are (see :mod:`tests.ui.test_import_layering`'s own
``_LEAF_PACKAGES`` docstring) -- they depend on ``dock_manager.py`` and the
services layer, same as ``main_window.py`` always did. What they must not
do is be imported *by* a leaf/widget module, which is why
``test_import_layering.py`` gained a "widgets never import controllers"
rule alongside this package's introduction.
"""

from __future__ import annotations
