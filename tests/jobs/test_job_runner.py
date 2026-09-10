# File: tests/jobs/test_job_runner.py
"""Characterize the :class:`JobRunner` protocol against a minimal fake.

This file exists to pin the *contract* independently of any real
implementation. The fake here — :class:`_SynchronousJobRunner` — is the
simplest thing that can satisfy :class:`JobRunner`: it runs ``fn`` inline
and calls the callbacks straight away, no threads. If the shared
:class:`~tests.jobs.job_runner_contract.JobRunnerContract` suite passes
against something this trivial, the contract is about *behaviour the
protocol promises*, not an accident of how
:class:`~uadas_core.jobs.thread_pool_executor_job_runner.ThreadPoolExecutorJobRunner`
happens to be built (that one re-runs the exact same suite in
``tests/jobs/test_thread_pool_executor_job_runner.py``).
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from tests.jobs.job_runner_contract import JobRunnerContract
from uadas_core.jobs.job_runner import JobRunner


class _SynchronousJobRunner:
    """A fake :class:`JobRunner` that runs ``fn`` inline on the calling thread.

    Only for tests: proves the contract is implementable without any
    concurrency machinery, so the contract suite is testing the promise
    rather than the thread pool.
    """

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
        if report_progress:
            kwargs["progress_callback"] = on_progress or (lambda *_: None)
        try:
            value = fn(*args, **kwargs)
            if on_result is not None:
                on_result(value)
        except Exception as exc:  # noqa: BLE001 - surfaced through on_error, by design
            if on_error is not None:
                on_error(exc, traceback.format_exc())
        finally:
            if on_finished is not None:
                on_finished()
        return object()


def test_fake_satisfies_the_job_runner_protocol() -> None:
    """A structural sanity check before the behavioural suite below runs."""
    runner: JobRunner = _SynchronousJobRunner()
    assert callable(runner.run)


class TestSynchronousJobRunnerContract(JobRunnerContract):
    """Run the shared contract against the inline fake."""

    def make_runner(self) -> JobRunner:
        return _SynchronousJobRunner()
