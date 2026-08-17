# File: src/workers/base_worker.py
"""Generic background-task execution via ``QThreadPool``.

Chosen over a raw ``QThread`` subclass per task: ``QRunnable`` +
``QThreadPool.globalInstance()`` reuses a pool of worker threads across
every call site in the application (dataset reads, dashboard
rendering, project reload today; AI streaming and report generation in
later milestones) rather than spinning up and tearing down a dedicated
``QThread`` object per operation. The one complication this trades in
return is that ``QRunnable`` itself cannot emit Qt signals (it is not
a ``QObject``), so :class:`WorkerSignals` exists purely to hold the
signals a ``QRunnable`` cannot own directly — :class:`BaseWorker`
composes one rather than trying to multiply-inherit ``QRunnable`` and
``QObject``, which Qt does not support cleanly through PySide6's
metaclass machinery.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

from src.core.logger import get_logger

_logger = get_logger(__name__)


class WorkerSignals(QObject):
    """The signals a :class:`BaseWorker` emits over its lifetime.

    A plain ``QRunnable`` cannot itself be a signal source, so every
    ``BaseWorker`` owns one of these and callers connect to
    ``worker.signals.<name>`` rather than to the worker directly.

    Signals:
        started: Emitted once, immediately before the wrapped callable
            runs, from the worker thread.
        progress: Emitted zero or more times if the wrapped callable
            accepts a ``progress_callback`` keyword argument and
            chooses to report progress through it. Carries an
            ``int`` (0-100) and a short status string.
        result: Emitted exactly once on success, carrying the wrapped
            callable's return value.
        error: Emitted exactly once on failure, carrying the raised
            exception and its formatted traceback string (captured on
            the worker thread, since the traceback object itself is
            not safe to hand across threads the way its string
            rendering is).
        finished: Emitted exactly once, after either ``result`` or
            ``error`` — the one signal callers can always connect to
            when they only care that the task is done, regardless of
            outcome (e.g. to hide a busy indicator).
    """

    started = Signal()
    progress = Signal(int, str)
    result = Signal(object)
    error = Signal(Exception, str)
    finished = Signal()


class BaseWorker(QRunnable):
    """Runs an arbitrary callable on a ``QThreadPool`` worker thread.

    Args:
        fn: The callable to execute off the UI thread. May be any
            callable — a bound method, a module-level function, a
            lambda — as long as it does not touch Qt widgets directly
            (Qt widgets are not thread-safe; results must flow back to
            the UI thread through ``signals.result``/``signals.error``
            and be applied there, not written to a widget from inside
            ``fn``).
        *args: Positional arguments passed to ``fn``.
        report_progress: If ``True``, a ``progress_callback`` keyword
            argument (itself a ``Callable[[int, str], None]`` that
            emits ``signals.progress``) is passed to ``fn``, letting
            long-running callables report incremental progress. Off
            by default since most call sites wrap a single opaque
            operation (a file read, a render) with no natural
            sub-steps to report.
        **kwargs: Keyword arguments passed to ``fn``.

    Usage:
        worker = BaseWorker(reader_class.read, dataset_path, table_name=table_name)
        worker.signals.result.connect(self._on_dataset_read)
        worker.signals.error.connect(self._on_dataset_read_error)
        worker.signals.finished.connect(self._hide_busy_indicator)
        QThreadPool.globalInstance().start(worker)
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        report_progress: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

        if report_progress:
            self._kwargs["progress_callback"] = self._emit_progress

    def _emit_progress(self, percent: int, message: str = "") -> None:
        self.signals.progress.emit(percent, message)

    def run(self) -> None:
        self.signals.started.emit()
        try:
            value = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 — deliberately broad: this is the
            # thread boundary. Any exception the wrapped callable raises must be
            # caught here and re-surfaced through signals.error on the UI thread,
            # since an exception escaping run() on a QThreadPool worker thread is
            # silently lost (Qt does not propagate it back to the caller) rather
            # than crashing the application or reaching any except block the
            # caller wrote — swallowing it here and forwarding it explicitly is
            # the only way the caller ever learns the task failed.
            _logger.warning("Background task %r failed: %s", self._fn, exc)
            self.signals.error.emit(exc, traceback.format_exc())
        else:
            self.signals.result.emit(value)
        finally:
            self.signals.finished.emit()
