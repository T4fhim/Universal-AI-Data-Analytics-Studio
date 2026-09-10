# File: tests/jobs/test_default_job_runner_registry.py
"""The Phase-1.2 default-runner bridge: set/get and the raise-if-unset branch.

``tests/core/test_bootstrap.py`` (step 6) covers the *installed* path —
``get_default_job_runner()`` after ``bootstrap()`` has run. This file
covers what that one cannot: the pre-install ``RuntimeError`` branch, and
replacement semantics, both of which need the module global reset around
each test (the same technique ``tests/conftest.py``'s
``reset_logging_state`` uses for ``logger._configured``).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import uadas_core.jobs as jobs_pkg
from uadas_core.jobs import get_default_job_runner, set_default_job_runner
from uadas_core.jobs.thread_pool_executor_job_runner import ThreadPoolExecutorJobRunner


@pytest.fixture(autouse=True)
def _isolate_default_runner() -> Iterator[None]:
    saved = jobs_pkg._default_job_runner
    jobs_pkg._default_job_runner = None
    try:
        yield
    finally:
        jobs_pkg._default_job_runner = saved


def test_get_raises_runtime_error_when_no_runner_installed() -> None:
    with pytest.raises(RuntimeError, match="No default JobRunner"):
        get_default_job_runner()


def test_set_then_get_returns_the_same_instance() -> None:
    runner = ThreadPoolExecutorJobRunner(max_workers=1)
    try:
        set_default_job_runner(runner)
        assert get_default_job_runner() is runner
    finally:
        runner.shutdown(wait=True)


def test_set_replaces_the_previous_runner() -> None:
    first = ThreadPoolExecutorJobRunner(max_workers=1)
    second = ThreadPoolExecutorJobRunner(max_workers=1)
    try:
        set_default_job_runner(first)
        set_default_job_runner(second)
        assert get_default_job_runner() is second
    finally:
        first.shutdown(wait=True)
        second.shutdown(wait=True)
