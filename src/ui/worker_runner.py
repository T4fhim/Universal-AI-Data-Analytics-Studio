# File: src/ui/worker_runner.py
"""Centralizes the "construct a BaseWorker, wire its signals, launch it" pattern.

Before milestone 19, every controller-shaped call site in ``main_window.py``
(dataset reads, project reload, dashboard rendering, report generation, AI
turns) repeated the same five lines: build a
:class:`~src.workers.base_worker.BaseWorker`, connect whichever of
``result``/``error``/``finished``/``progress`` it cared about, then call
``QThreadPool.globalInstance().start(worker)``. :class:`WorkerRunner` is
that repetition factored into one place so the milestone-19 controllers
(:mod:`src.ui.controllers`) each write one call instead of five lines of
boilerplate -- it does not change :class:`~src.workers.base_worker.BaseWorker`
itself or any of its threading semantics (see that module's own docstring
for those), it only removes the ceremony of wiring it up.

A thin :class:`QObject` rather than a set of free functions purely so a
controller can hold one ``WorkerRunner`` instance and pass it around the
same way it already holds a ``dock_manager``/``status_bar`` reference --
nothing here actually depends on ``QObject`` parenting for correctness
(``BaseWorker``/``QThreadPool`` do not require a parent), it is only for
consistency with how every other collaborator in this package is held.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThreadPool

from src.workers import BaseWorker


class WorkerRunner(QObject):
    """Launches a callable on the global ``QThreadPool``, wiring the callbacks given.

    Args:
        parent: Optional Qt parent, purely for lifetime bookkeeping
            consistency with the rest of this package -- see the module
            docstring for why this class does not otherwise need one.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_result: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception, str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        on_progress: Callable[[int, str], None] | None = None,
        report_progress: bool = False,
        **kwargs: Any,
    ) -> BaseWorker:
        """Run ``fn(*args, **kwargs)`` off the UI thread and route its signals.

        Args:
            fn: The callable to execute -- same constraints as
                :class:`~src.workers.base_worker.BaseWorker`'s own ``fn``
                (must not touch Qt widgets directly).
            on_result: Connected to ``signals.result`` if given.
            on_error: Connected to ``signals.error`` if given.
            on_finished: Connected to ``signals.finished`` if given.
            on_progress: Connected to ``signals.progress`` if given.
            report_progress: Forwarded to ``BaseWorker`` unchanged -- see
                its own docstring for what this adds to ``fn``'s call.

        Returns:
            The started :class:`~src.workers.base_worker.BaseWorker`, in
            case a caller needs to retain a reference to it (e.g. to know
            a background task is currently in flight) -- the worker itself
            is already handed to the thread pool by the time this returns,
            so nothing further needs to be done with it to run it.
        """
        worker = BaseWorker(fn, *args, report_progress=report_progress, **kwargs)
        if on_result is not None:
            worker.signals.result.connect(on_result)
        if on_error is not None:
            worker.signals.error.connect(on_error)
        if on_finished is not None:
            worker.signals.finished.connect(on_finished)
        if on_progress is not None:
            worker.signals.progress.connect(on_progress)
        QThreadPool.globalInstance().start(worker)
        return worker
