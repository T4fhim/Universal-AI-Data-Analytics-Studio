# File: tests/ui/test_worker_runner.py
"""Tests for WorkerRunner, the milestone-19 BaseWorker-wiring helper.

Uses a recording thread-pool stand-in (the same pattern
``tests/ui/widgets/data_table/test_data_table_view.py`` established) rather
than the real ``QThreadPool`` -- deterministic assertions about *what was
wired* would otherwise race a real background thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from src.ui.worker_runner import WorkerRunner


class _RecordingThreadPool:
    def __init__(self) -> None:
        self.started_workers: list = []

    def start(self, worker) -> None:
        self.started_workers.append(worker)


def _add(a: int, b: int) -> int:
    return a + b


def _boom() -> None:
    raise ValueError("boom")


def test_run_starts_exactly_one_worker_on_the_global_thread_pool(
    qapp: QApplication, monkeypatch
) -> None:
    pool = _RecordingThreadPool()
    monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: pool))

    runner = WorkerRunner()
    runner.run(_add, 2, 3)

    assert len(pool.started_workers) == 1


def test_run_returns_the_started_worker(qapp: QApplication, monkeypatch) -> None:
    pool = _RecordingThreadPool()
    monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: pool))

    runner = WorkerRunner()
    worker = runner.run(_add, 2, 3)

    assert worker is pool.started_workers[0]


def test_on_result_is_wired_and_fires_with_the_return_value(qapp: QApplication) -> None:
    """Real QThreadPool this time -- proving the callback actually reaches
    the caller end to end, not just that it was connect()-ed.
    """
    from tests.ui.qt_helpers import wait_for_signal

    runner = WorkerRunner()
    received: list[int] = []
    worker = runner.run(_add, 2, 3, on_result=received.append)
    wait_for_signal(worker.signals.finished)

    assert received == [5]


def test_on_error_is_wired_and_fires_with_the_exception(qapp: QApplication) -> None:
    from tests.ui.qt_helpers import wait_for_signal

    runner = WorkerRunner()
    received: list[Exception] = []
    worker = runner.run(_boom, on_error=lambda exc, tb: received.append(exc))
    wait_for_signal(worker.signals.finished)

    assert len(received) == 1
    assert isinstance(received[0], ValueError)


def test_on_progress_and_report_progress_are_forwarded_to_baseworker(
    qapp: QApplication, monkeypatch
) -> None:
    """report_progress=True must reach BaseWorker unchanged -- asserted by
    checking BaseWorker actually received a progress_callback kwarg, since
    that is the only externally visible effect of the flag from here.
    """
    pool = _RecordingThreadPool()
    monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: pool))

    runner = WorkerRunner()

    def _fn(progress_callback=None) -> None:
        pass

    runner.run(_fn, report_progress=True, on_progress=lambda pct, msg: None)

    worker = pool.started_workers[0]
    assert "progress_callback" in worker._kwargs


def test_a_raising_on_result_is_never_silently_lost(
    qapp: QApplication, block_modals
) -> None:
    """Regression test for the real reported defect: a dataset load's own
    reader logged success, but neither of ``DatasetController.load_dataset``'s
    own log lines ever appeared -- meaning ``on_result`` started, then failed
    silently partway through. ``BaseWorker``'s own docstring already names
    this exact class of failure for exceptions raised by the wrapped
    callable ``fn`` itself (caught by ``run()``'s own try/except); this test
    proves the equivalent failure in the *connected callback* -- previously
    uncaught anywhere -- is now surfaced too: logged, and shown to the user
    via ``QMessageBox.critical`` (intercepted here by the autouse
    ``block_modals`` fixture rather than actually blocking the test).
    """
    from tests.ui.qt_helpers import wait_for_signal

    def _raising_on_result(_value: int) -> None:
        raise ValueError("simulated failure inside on_result")

    runner = WorkerRunner()
    worker = runner.run(_add, 2, 3, on_result=_raising_on_result)
    # The worker itself must still finish cleanly -- a raising on_result must
    # not prevent signals.finished from firing (it already ran by this point
    # in BaseWorker.run()'s own finally block; this just proves the guard
    # didn't somehow re-raise into and kill anything downstream).
    wait_for_signal(worker.signals.finished)

    critical_calls = [call for call in block_modals if call.kind == "critical"]
    assert len(critical_calls) == 1
    assert "simulated failure inside on_result" in critical_calls[0].text


def test_a_raising_on_finished_is_never_silently_lost(
    qapp: QApplication, block_modals
) -> None:
    """Same guarantee, for on_finished -- a separate connect() call site with
    its own independent ``_guarded()`` wrapping, not exercised by the
    on_result test above.

    Calls ``_guarded()`` directly rather than going through a real
    ``QThreadPool`` worker the way the on_result test above does. Two prior
    versions of this test drove the real worker + event-loop-pumping path
    (``wait_for_signal`` on a second listener, then a bounded
    ``process_events()`` poll) and both were genuinely unsafe under
    full-suite load when run alongside ``tests/ui/widgets/test_chart_view.py``:
    the first flaked (a one-shot-signal connect-after-emit race -- a second
    listener attached after ``run()`` returns can miss an emission that
    already happened and fully delivered), and the second caused a real
    ``Windows fatal exception: access violation`` inside ``process_events()``
    -- the same class of Windows ``QWebEngineView`` teardown crash this
    project's own pyside6-development skill already documents, triggered by
    pumping the event loop while a neighboring WebEngine test's teardown is
    in flight. ``_guarded()`` itself has no threading or event-loop
    dependency (see its own docstring) -- calling it synchronously proves
    the wrapper's per-callback-type behavior (the "finished handler" label
    in the error dialog text) without either risk. The on_result test above
    already proves the real ``QThreadPool`` -> queued-connection -> guard
    integration end to end for one callback type; this one intentionally
    trades that integration coverage for the crash-free, deterministic path.
    """
    from src.ui.worker_runner import _guarded

    def _raising_on_finished() -> None:
        raise RuntimeError("simulated failure inside on_finished")

    _guarded("finished handler", _raising_on_finished)()

    critical_calls = [call for call in block_modals if call.kind == "critical"]
    assert len(critical_calls) == 1
    assert "simulated failure inside on_finished" in critical_calls[0].text
    assert "finished handler" in critical_calls[0].text
