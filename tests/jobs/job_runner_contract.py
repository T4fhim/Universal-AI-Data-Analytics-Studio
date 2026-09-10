# File: tests/jobs/job_runner_contract.py
"""Shared characterization suite every :class:`JobRunner` implementation must pass.

The desktop→web transition only works if a future out-of-process
``DjangoTasksJobRunner`` is a *drop-in* for today's
:class:`~uadas_core.jobs.thread_pool_executor_job_runner.ThreadPoolExecutorJobRunner`.
That guarantee is only real if the contract is pinned by tests that run
against *every* implementation, not just the one that happens to exist.

:class:`JobRunnerContract` is that suite. It is deliberately **not**
named ``Test*`` so pytest does not collect it on its own (it has no
concrete runner). Each implementation's test module subclasses it with a
one-line :meth:`make_runner` override — mirroring how
``tests/ui/qt_helpers.py`` is a plain importable helper rather than a
test file.

The suite is written to work for a synchronous runner (a fake) *and* an
asynchronous one (a real thread pool): every job is submitted through
:meth:`_run_and_wait`, which blocks on the contractually-guaranteed
``on_finished`` callback rather than assuming ``run()`` has already
completed the work by the time it returns.
"""

from __future__ import annotations

import threading
from typing import Any

from uadas_core.jobs.job_runner import JobRunner

_WAIT_TIMEOUT_SECONDS = 5.0


class CallbackRecorder:
    """Collects everything a job's callbacks were handed, for later assertions."""

    def __init__(self) -> None:
        self.results: list[Any] = []
        self.errors: list[tuple[BaseException, str]] = []
        self.progress: list[tuple[int, str]] = []
        self.finished_count = 0
        self._done = threading.Event()

    # --- callbacks handed to JobRunner.run() -------------------------------

    def on_result(self, value: Any) -> None:
        self.results.append(value)

    def on_error(self, exc: Exception, tb: str) -> None:
        self.errors.append((exc, tb))

    def on_progress(self, percent: int, message: str) -> None:
        self.progress.append((percent, message))

    def on_finished(self) -> None:
        self.finished_count += 1
        self._done.set()

    # --- test-side helper ------------------------------------------------

    def wait(self) -> None:
        if not self._done.wait(
            _WAIT_TIMEOUT_SECONDS
        ):  # pragma: no cover - failure path
            raise AssertionError(
                "on_finished never fired within "
                f"{_WAIT_TIMEOUT_SECONDS}s — the runner violated the "
                "'on_finished always runs' contract or deadlocked."
            )


class JobRunnerContract:
    """Behavioural contract shared by every :class:`JobRunner` implementation."""

    def make_runner(self) -> JobRunner:
        """Return a fresh runner under test. Overridden per implementation."""
        raise NotImplementedError

    # -- helpers ---------------------------------------------------------

    def _run_and_wait(
        self,
        recorder: CallbackRecorder,
        fn: Any,
        *args: Any,
        report_progress: bool = False,
        **kwargs: Any,
    ) -> Any:
        runner = self.make_runner()
        handle = runner.run(
            fn,
            *args,
            report_progress=report_progress,
            on_result=recorder.on_result,
            on_error=recorder.on_error,
            on_finished=recorder.on_finished,
            on_progress=recorder.on_progress,
            **kwargs,
        )
        recorder.wait()
        return handle

    # -- the contract --------------------------------------------------

    def test_on_result_fires_once_with_return_value_and_no_error(self) -> None:
        recorder = CallbackRecorder()
        self._run_and_wait(recorder, lambda: 21 * 2)

        assert recorder.results == [42]
        assert recorder.errors == []
        assert recorder.finished_count == 1

    def test_fn_receives_positional_and_keyword_arguments(self) -> None:
        recorder = CallbackRecorder()

        def _fn(a: int, b: int, *, c: int) -> int:
            return a + b + c

        self._run_and_wait(recorder, _fn, 1, 2, c=3)

        assert recorder.results == [6]

    def test_on_error_fires_once_with_exception_and_traceback_string(self) -> None:
        recorder = CallbackRecorder()
        sentinel = RuntimeError("kaboom")

        def _fn() -> None:
            raise sentinel

        self._run_and_wait(recorder, _fn)

        assert recorder.results == []
        assert len(recorder.errors) == 1
        exc, tb = recorder.errors[0]
        assert exc is sentinel
        assert isinstance(tb, str)
        # A formatted traceback string, not the exception's repr — the
        # point of the separate second argument.
        assert "Traceback (most recent call last)" in tb
        assert "kaboom" in tb
        assert recorder.finished_count == 1

    def test_result_and_error_are_mutually_exclusive(self) -> None:
        ok = CallbackRecorder()
        self._run_and_wait(ok, lambda: "value")
        assert bool(ok.results) != bool(ok.errors)

        boom = CallbackRecorder()

        def _raise() -> None:
            raise ValueError("no")

        self._run_and_wait(boom, _raise)
        assert bool(boom.results) != bool(boom.errors)

    def test_on_finished_fires_even_with_no_result_or_error_callbacks(self) -> None:
        runner = self.make_runner()
        done = threading.Event()
        runner.run(lambda: None, on_finished=done.set)
        assert done.wait(_WAIT_TIMEOUT_SECONDS), "on_finished must fire unconditionally"

    def test_progress_callback_injected_and_forwarded_when_requested(self) -> None:
        recorder = CallbackRecorder()

        def _fn(*, progress_callback: Any) -> str:
            progress_callback(10, "starting")
            progress_callback(100, "done")
            return "ok"

        self._run_and_wait(recorder, _fn, report_progress=True)

        assert recorder.progress == [(10, "starting"), (100, "done")]
        assert recorder.results == ["ok"]

    def test_no_progress_callback_injected_when_not_requested(self) -> None:
        recorder = CallbackRecorder()
        seen: dict[str, bool] = {}

        def _fn(**kwargs: Any) -> None:
            seen["has_progress_callback"] = "progress_callback" in kwargs

        self._run_and_wait(recorder, _fn, report_progress=False)

        assert seen == {"has_progress_callback": False}
        assert recorder.progress == []

    def test_run_returns_a_handle(self) -> None:
        recorder = CallbackRecorder()
        handle = self._run_and_wait(recorder, lambda: 1)
        assert handle is not None
