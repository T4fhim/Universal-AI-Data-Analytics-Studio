# File: tests/jobs/test_thread_pool_executor_job_runner.py
"""The real :class:`ThreadPoolExecutorJobRunner` against the shared contract.

:class:`TestThreadPoolExecutorJobRunnerContract` reuses the exact same
:class:`~tests.jobs.job_runner_contract.JobRunnerContract` the inline fake
passes in ``tests/jobs/test_job_runner.py`` — if both pass, the contract
is genuinely implementation-independent, which is the whole premise of
being able to swap in an out-of-process runner in Phase 3.

The extra :func:`test_ten_concurrent_jobs_each_get_their_own_callbacks`
covers the one thing a synchronous fake can't: real concurrency. With
``max_workers`` smaller than the job count, jobs must queue and every one
must still deliver its *own* result and progress with no cross-talk
between callback streams.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.jobs.job_runner_contract import CallbackRecorder, JobRunnerContract
from uadas_core.jobs.job_runner import JobRunner
from uadas_core.jobs.thread_pool_executor_job_runner import (
    SimpleJobHandle,
    ThreadPoolExecutorJobRunner,
)


class TestThreadPoolExecutorJobRunnerContract(JobRunnerContract):
    """Run the shared behavioural contract against the real thread pool."""

    @pytest.fixture(autouse=True)
    def _shutdown_created_runners(self) -> Iterator[None]:
        # Every make_runner() call spins up a real ThreadPoolExecutor;
        # without this the suite would leak idle worker threads into the
        # long-lived pytest process (exactly the kind of teardown-time
        # fragility run_tests_and_exit_cleanly.py exists to work around).
        self._created: list[ThreadPoolExecutorJobRunner] = []
        yield
        for runner in self._created:
            runner.shutdown(wait=True)

    def make_runner(self) -> JobRunner:
        runner = ThreadPoolExecutorJobRunner(max_workers=4)
        self._created.append(runner)
        return runner


def test_run_returns_a_simple_job_handle() -> None:
    runner = ThreadPoolExecutorJobRunner(max_workers=1)
    try:
        done = CallbackRecorder()
        handle = runner.run(lambda: 1, on_finished=done.on_finished)
        done.wait()
        assert isinstance(handle, SimpleJobHandle)
        assert handle.id  # a non-empty uuid string
    finally:
        runner.shutdown(wait=True)


def test_ten_concurrent_jobs_each_get_their_own_callbacks() -> None:
    """max_workers=4, 10 jobs: all queue, all finish, zero callback cross-talk."""
    job_count = 10
    runner = ThreadPoolExecutorJobRunner(max_workers=4)
    recorders = [CallbackRecorder() for _ in range(job_count)]

    def make_fn(index: int):
        def _fn(*, progress_callback) -> int:
            progress_callback(50, f"half-{index}")
            progress_callback(100, f"done-{index}")
            return index * 10

        return _fn

    try:
        for index, recorder in enumerate(recorders):
            runner.run(
                make_fn(index),
                report_progress=True,
                on_result=recorder.on_result,
                on_progress=recorder.on_progress,
                on_finished=recorder.on_finished,
            )

        for recorder in recorders:
            recorder.wait()
    finally:
        runner.shutdown(wait=True)

    for index, recorder in enumerate(recorders):
        assert recorder.results == [index * 10]
        assert recorder.progress == [
            (50, f"half-{index}"),
            (100, f"done-{index}"),
        ]
        assert recorder.errors == []
        assert recorder.finished_count == 1
