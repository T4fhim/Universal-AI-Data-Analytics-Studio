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
