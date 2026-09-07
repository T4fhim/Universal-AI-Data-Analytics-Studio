# File: tests/ui/test_base_worker_adapter.py
"""Characterize BaseWorker as a QThreadPool -> JobRunner adapter (web-transition Phase 1.2).

``tests/ui/test_worker_runner.py`` already covers ``WorkerRunner`` wiring
and the real-``QThreadPool`` end-to-end path, and the de-risking plan's
Control A10 forbids editing it. This file is the *new* coverage that step
7 needs: that ``BaseWorker.run()`` delegates to the resolved
:class:`~uadas_core.jobs.job_runner.JobRunner` with the caller's exact
arguments, that it re-emits the runner's callbacks as Qt signals in the
documented order, and that it honours ``QThreadPool``'s "run() is
synchronous" contract by blocking until the terminal callback fires.

A recording fake stands in for the runner (installed via
``set_default_job_runner``) so these assertions are about *what BaseWorker
asked the runner to do*, deterministically, without racing a real
background thread.
"""

from __future__ import annotations

import inspect
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication

import uadas_core.jobs as jobs_pkg
from src.workers.base_worker import BaseWorker, WorkerSignals
from uadas_core.jobs import set_default_job_runner


class _RecordedCall:
    def __init__(self, fn: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.report_progress: bool = False
        self.on_result: Callable[[Any], None] | None = None
        self.on_error: Callable[[Exception, str], None] | None = None
        self.on_finished: Callable[[], None] | None = None
        self.on_progress: Callable[[int, str], None] | None = None


class _RecordingJobRunner:
    """A JobRunner that records the call and drives the callbacks synchronously.

    ``drive`` controls what it does after recording:
        "result"  - run fn, then on_result(return value), then on_finished
        "error"   - run fn (expected to raise), then on_error, then on_finished
        "defer"   - record only; the test invokes the callbacks itself
    """

    def __init__(self, drive: str = "result") -> None:
        self.calls: list[_RecordedCall] = []
        self._drive = drive

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        report_progress: bool = False,
        on_result: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception, str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        on_progress: Callable[[int, str], None] | None = None,
        **kwargs: Any,
    ) -> object:
        call = _RecordedCall(fn, args, dict(kwargs))
        call.report_progress = report_progress
        call.on_result = on_result
        call.on_error = on_error
        call.on_finished = on_finished
        call.on_progress = on_progress
        self.calls.append(call)

        if self._drive == "defer":
            return object()

        try:
            value = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - mimics the real runner's boundary
            if on_error is not None:
                on_error(exc, traceback.format_exc())
        else:
            if on_result is not None:
                on_result(value)
        finally:
            if on_finished is not None:
                on_finished()
        return object()


@pytest.fixture
def install_runner() -> Iterator[Callable[[Any], Any]]:
    """Install a default JobRunner for the test, restoring the module global after."""
    saved = jobs_pkg._default_job_runner

    def _install(runner: Any) -> Any:
        set_default_job_runner(runner)
        return runner

    try:
        yield _install
    finally:
        jobs_pkg._default_job_runner = saved


def _order_recorder(worker: BaseWorker) -> list[str]:
    seen: list[str] = []
    worker.signals.started.connect(lambda: seen.append("started"))
    worker.signals.progress.connect(lambda _p, _m: seen.append("progress"))
    worker.signals.result.connect(lambda _v: seen.append("result"))
    worker.signals.error.connect(lambda _e, _tb: seen.append("error"))
    worker.signals.finished.connect(lambda: seen.append("finished"))
    return seen


def test_run_delegates_to_resolved_runner_with_the_callers_exact_arguments(
    qapp: QApplication, install_runner: Callable[[Any], Any]
) -> None:
    runner = install_runner(_RecordingJobRunner(drive="defer"))

    def mock_fn(*_a: Any, **_k: Any) -> str:
        return "ignored"

    worker = BaseWorker(mock_fn, 1, 2, foo="bar", report_progress=True)
    # drive="defer" recorded the call but did not fire on_finished, so
    # release run()'s wait manually once we've captured the call.
    threading.Thread(target=worker.run, daemon=True).start()
    _wait_until(lambda: bool(runner.calls))
    call = runner.calls[0]
    assert call.on_finished is not None
    call.on_finished()

    assert len(runner.calls) == 1
    assert call.fn is mock_fn
    assert call.args == (1, 2)
    assert call.kwargs["foo"] == "bar"
    # __init__ (unchanged) injected the worker's own progress forwarder
    # into self._kwargs; run() passes **self._kwargs straight through.
    assert call.kwargs["progress_callback"] == worker._emit_progress
    # BaseWorker does NOT use the runner's own report_progress mechanism -
    # its progress_callback is already in kwargs (see run()'s comment).
    assert call.report_progress is False
    # The three terminal callbacks are wired to signal emitters.
    assert callable(call.on_result)
    assert callable(call.on_error)
    assert callable(call.on_finished)


def test_signals_emit_in_order_started_progress_result_finished(
    qapp: QApplication, install_runner: Callable[[Any], Any]
) -> None:
    install_runner(_RecordingJobRunner(drive="result"))

    def fn_with_progress(*, progress_callback: Callable[[int, str], None]) -> int:
        progress_callback(50, "half")
        return 7

    worker = BaseWorker(fn_with_progress, report_progress=True)
    order = _order_recorder(worker)

    worker.run()

    assert order == ["started", "progress", "result", "finished"]


def test_signals_emit_in_order_started_error_finished_when_fn_raises(
    qapp: QApplication, install_runner: Callable[[Any], Any]
) -> None:
    install_runner(_RecordingJobRunner(drive="error"))
    boom = RuntimeError("worker fn failed")

    def fn_that_raises() -> None:
        raise boom

    worker = BaseWorker(fn_that_raises)
    order = _order_recorder(worker)
    errors: list[tuple[Exception, str]] = []
    worker.signals.error.connect(lambda exc, tb: errors.append((exc, tb)))

    worker.run()

    assert order == ["started", "error", "finished"]
    assert "result" not in order
    assert len(errors) == 1
    exc, tb = errors[0]
    assert exc is boom
    assert "worker fn failed" in tb


def test_run_blocks_until_on_finished_fires(
    qapp: QApplication, install_runner: Callable[[Any], Any]
) -> None:
    """QThreadPool's contract: run() must not return before the job is done."""
    runner = install_runner(_RecordingJobRunner(drive="defer"))
    worker = BaseWorker(lambda: None)

    returned = threading.Event()

    def _call_run() -> None:
        worker.run()
        returned.set()

    threading.Thread(target=_call_run, daemon=True).start()
    _wait_until(lambda: bool(runner.calls))

    # The runner has been called but nothing fired on_finished yet.
    assert not returned.wait(0.2), "run() returned before on_finished fired"

    runner.calls[0].on_finished()  # type: ignore[misc]
    assert returned.wait(2.0), "run() did not return after on_finished fired"


def test_worker_signals_and_constructor_signature_are_unchanged(
    qapp: QApplication,
) -> None:
    """Control A10 guard: the public shape BaseWorker's call sites depend on."""
    params = list(inspect.signature(BaseWorker.__init__).parameters.values())
    names = [p.name for p in params]
    assert names == ["self", "fn", "args", "report_progress", "kwargs"]
    report_progress = inspect.signature(BaseWorker.__init__).parameters[
        "report_progress"
    ]
    assert report_progress.default is False
    assert report_progress.kind is inspect.Parameter.KEYWORD_ONLY

    for name in ("started", "progress", "result", "error", "finished"):
        assert isinstance(vars(WorkerSignals)[name], Signal)


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met within timeout")


# --- 1.2 code-review follow-ups -------------------------------------------------


def test_resolve_job_runner_falls_back_to_one_cached_pool_without_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No bootstrap => a single lazily-built local pool, cached (double-checked lock).

    Covers the review-flagged gap: nothing exercised the ``_resolve_job_runner``
    fallback branch. Repeated calls must return the *same* object so concurrent
    ``QThreadPool`` workers cannot end up on separate pools (8 threads instead of 4).
    """
    import src.workers.base_worker as bw
    from uadas_core.jobs.thread_pool_executor_job_runner import (
        ThreadPoolExecutorJobRunner,
    )

    monkeypatch.setattr(jobs_pkg, "_default_job_runner", None)
    monkeypatch.setattr(bw, "_fallback_job_runner", None)

    first = bw._resolve_job_runner()
    second = bw._resolve_job_runner()
    assert isinstance(first, ThreadPoolExecutorJobRunner)
    assert first is second


# The companion deadlock guard (``_on_finished`` wraps ``signals.finished.emit()``
# in try/finally so ``done.set()`` always runs, even if a ``finished`` slot raises)
# is verified by inspection + code review rather than a live test: pytest-qt
# auto-fails any test in which a Qt slot raises, so exercising the raising-slot
# path here would fail the harness regardless of the guard.
