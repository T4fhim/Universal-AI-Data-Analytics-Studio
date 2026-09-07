# File: src/workers/base_worker.py
"""``QThreadPool`` adapter over the Qt-free :class:`~uadas_core.jobs.job_runner.JobRunner`.

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

**Web-transition Phase 1.2:** the actual "run ``fn`` off the calling
thread, report the outcome through callbacks" policy no longer lives in
:meth:`BaseWorker.run` — it moved to :mod:`uadas_core.jobs`, which carries
no GUI-toolkit dependency and can be re-implemented against an
out-of-process task queue in Phase 3. ``BaseWorker`` is now a thin
adapter: ``QThreadPool`` still calls :meth:`run` on a pool thread, but
that method hands the work to the process-wide
:class:`~uadas_core.jobs.job_runner.JobRunner` and re-emits its callbacks
as Qt signals, so the ``QueuedConnection`` wiring in
:mod:`src.ui.worker_runner` marshals them to the UI thread exactly as
before. This whole ``src/workers/`` shell — ``BaseWorker`` included — is
deleted in Phase 2; nothing new should be built on it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

from uadas_core.core.logger import get_logger
from uadas_core.jobs import get_default_job_runner
from uadas_core.jobs.job_runner import JobRunner
from uadas_core.jobs.thread_pool_executor_job_runner import ThreadPoolExecutorJobRunner

_logger = get_logger(__name__)


# Phase-1.2 fallback. In a real application session ``bootstrap()`` installs
# the process-wide JobRunner (the same instance ``container.resolve(JobRunner)``
# hands out — one pool), so :func:`_resolve_job_runner` returns that. This
# lazily-built local pool covers the one context that never runs
# ``bootstrap()``: ``tests/ui/test_worker_runner.py``, which the de-risking
# plan's Control A10 forbids editing. Without it, ``get_default_job_runner()``
# would raise on the ``QThreadPool`` worker thread, where Qt silently swallows
# the exception and ``signals.finished`` would never fire. A second module
# global in a shell that is deleted in Phase 2 — deliberately scoped, noted
# for the 1.3 de-globalization pass alongside ``uadas_core.jobs``'s own bridge.
_fallback_job_runner: JobRunner | None = None


def _resolve_job_runner() -> JobRunner:
    """Return the bootstrap-installed :class:`JobRunner`, or a local fallback pool."""
    global _fallback_job_runner
    try:
        return get_default_job_runner()
    except RuntimeError:
        if _fallback_job_runner is None:
            _fallback_job_runner = ThreadPoolExecutorJobRunner()
        return _fallback_job_runner


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
        # Milestone-28 remediation, part 2 -- root cause of the defect the [diag] logs
        # below were added to chase: QRunnable.autoDelete() defaults to True, so
        # QThreadPool deleted this runnable within microseconds of run() returning.
        # self.signals (constructed with no QObject parent, just below) had no other
        # owner, so it went down with it -- racing the UI thread's delivery of the
        # result/finished queued-connection events run() had *just* posted, and
        # sometimes losing: real application.log evidence (2026-08-24) showed the
        # "finished" handler's queued delivery failing 5/5 real dataset-load attempts
        # and "result" failing 1/5 -- finished is emitted the instant before run()
        # returns (near-zero headroom before deletion), result slightly earlier (more
        # headroom, but not immune). WorkerRunner.run() now keeps a strong reference to
        # this worker for exactly as long as needed instead of relying on
        # QThreadPool's auto-delete timing -- see that method's own comment; this call
        # is the other half of that fix; without it QThreadPool would still delete the
        # runnable regardless of what WorkerRunner holds onto in Python.
        self.setAutoDelete(False)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()

        if report_progress:
            self._kwargs["progress_callback"] = self._emit_progress

    def _emit_progress(self, percent: int, message: str = "") -> None:
        self.signals.progress.emit(percent, message)

    def run(self) -> None:
        """Hand the work to the :class:`JobRunner` and re-emit its callbacks as signals.

        Called by ``QThreadPool`` on a pool thread. The wrapped ``fn`` is
        no longer invoked here directly — :func:`_resolve_job_runner`
        returns the Qt-free
        :class:`~uadas_core.jobs.job_runner.JobRunner`, and this method
        wires its ``on_result`` / ``on_error`` / ``on_finished`` callbacks
        to ``self.signals.*``. Qt's existing ``QueuedConnection`` (see
        :mod:`src.ui.worker_runner`) still marshals those emissions to the
        UI thread.

        Why still catch every exception: an exception escaping ``run()``
        on a ``QThreadPool`` worker thread is silently lost (Qt does not
        propagate it back to the caller). That responsibility now lives in
        the ``JobRunner`` — it turns any exception from ``fn`` into an
        ``on_error(exc, traceback_str)`` call rather than letting it
        vanish — but the reason it matters is unchanged, which is why
        :mod:`src.ui.worker_runner`'s own guard still references this.

        Why block on an :class:`threading.Event`: ``QThreadPool``'s
        contract is that ``run()`` returns only once the task is done. The
        ``JobRunner`` may complete the job on a *different* thread, so this
        pool thread waits on ``done`` until the terminal callback has
        fired. The two thread pools are independent, so this wait cannot
        self-deadlock (asserted by ``tests/ui/test_worker_runner.py`` and
        the full suite).
        """
        self.signals.started.emit()

        done = threading.Event()

        def _on_result(value: object) -> None:
            self.signals.result.emit(value)

        def _on_error(exc: Exception, formatted_traceback: str) -> None:
            _logger.warning("Background task %r failed: %s", self._fn, exc)
            self.signals.error.emit(exc, formatted_traceback)

        def _on_finished() -> None:
            # Emitted before done.set() unblocks run(), so finished is
            # posted while this worker (and self.signals) is still held
            # alive by the run() frame on the stack -- see __init__'s
            # setAutoDelete(False) comment for the race this closes.
            self.signals.finished.emit()
            done.set()

        # report_progress is intentionally NOT forwarded to the JobRunner:
        # __init__ (unchanged) already injected self._emit_progress into
        # self._kwargs under the "progress_callback" key when the caller
        # asked for progress, so self._kwargs already carries everything fn
        # needs. Passing report_progress here too would just make the
        # runner overwrite that with an equivalent forwarder.
        _resolve_job_runner().run(
            self._fn,
            *self._args,
            on_result=_on_result,
            on_error=_on_error,
            on_finished=_on_finished,
            **self._kwargs,
        )

        done.wait()
