# File: uadas_core/jobs/thread_pool_executor_job_runner.py
"""In-process :class:`JobRunner` — the desktop and single-node default.

This is the only :class:`~uadas_core.jobs.job_runner.JobRunner`
implementation as of Phase 1.2. It runs each job on a shared
``concurrent.futures.ThreadPoolExecutor`` and invokes the callbacks from
the pool thread that ran the job.

Why a bounded pool rather than a thread per job (which is what the
``QThread``-based :class:`~src.workers.base_worker.BaseWorker` effectively
did before this): the same reason ``BaseWorker`` itself sat on
``QThreadPool`` — every call site in the app (dataset reads, dashboard
renders, project reload, AI turns, report generation) funnels through one
runner, so an unbounded fan-out of OS threads is a real risk worth
capping. ``max_workers=4`` is the desktop default; a server deployment
tuning this is expected and is a constructor argument, not a constant.
*(Unverified: no desktop profiling data behind the 4 — see
``plans/phase-1-2-jobrunner-design.md``. Pool saturation is observable:
jobs queue rather than fail.)*

Callbacks run on the pool thread. A consumer that needs them on a
particular thread — :class:`~src.workers.base_worker.BaseWorker` marshals
them onto the Qt UI thread by re-emitting them as queued signals — does
that itself; see :class:`~uadas_core.jobs.job_runner.JobRunner`'s
docstring for why thread affinity is deliberately not this layer's job.

No cancellation: :func:`concurrent.futures.Executor.submit` returns a
``Future`` this class deliberately drops, because a future is exactly the
thing that will *not* survive Phase 3's move to an out-of-process task
queue (see the protocol module). Callers get an opaque
:class:`SimpleJobHandle` instead.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, TypeVar
from uuid import uuid4

from uadas_core.core.logger import get_logger

T = TypeVar("T")

_DEFAULT_MAX_WORKERS = 4
_logger = get_logger(__name__)


@dataclass(frozen=True)
class SimpleJobHandle:
    """The Phase 1.2 :class:`~uadas_core.jobs.job_runner.JobHandle`.

    Carries a uuid used only for logging/bookkeeping — nothing in 1.2
    looks the job up by it. Frozen so a caller cannot mistake it for a
    mutable status object; treat it as an opaque token (Phase 3 is
    expected to swap the whole type for a task id — see the protocol
    module).
    """

    id: str = field(default_factory=lambda: str(uuid4()))


class ThreadPoolExecutorJobRunner:
    """Runs jobs on a shared bounded thread pool. Implements :class:`JobRunner`."""

    def __init__(self, max_workers: int = _DEFAULT_MAX_WORKERS) -> None:
        # thread_name_prefix so these threads are identifiable in a
        # faulthandler dump or a debugger — the app runs Qt threads,
        # asyncio threads (later), and these, in one process.
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="uadas-job"
        )

    def run(
        self,
        fn: Callable[..., T],
        *args: Any,
        report_progress: bool = False,
        on_result: Callable[[T], None] | None = None,
        on_error: Callable[[Exception, str], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        on_progress: Callable[[int, str], None] | None = None,
        **kwargs: Any,
    ) -> SimpleJobHandle:
        """See :meth:`~uadas_core.jobs.job_runner.JobRunner.run` for the contract."""
        if report_progress:
            # Injected unconditionally when requested so ``fn`` can call
            # ``progress_callback(pct, msg)`` without guarding on whether a
            # listener exists — the no-listener case is an explicit no-op,
            # matching what BaseWorker.__init__ does today.
            kwargs["progress_callback"] = on_progress or (lambda *_: None)

        def _run_callback(cb: Callable[..., None] | None, *cb_args: Any) -> None:
            # A callback that itself raises must not escape into the discarded
            # Future (where the executor swallows it) -- the job's own outcome is
            # already decided; a broken listener is the listener's bug, logged
            # here so it is not silent (whole-branch diagnosis, LOW).
            if cb is None:
                return
            try:
                cb(*cb_args)
            except Exception:
                _logger.exception(
                    "A JobRunner callback (%s) raised; the job's outcome is unaffected.",
                    getattr(cb, "__name__", cb),
                )

        def _wrapped() -> None:
            try:
                value = fn(*args, **kwargs)
            except Exception as exc:
                # exception from ``fn`` must be reported via ``on_error`` rather
                # than allowed to escape the pool thread, where it would be
                # swallowed by the executor and surface only as a dead job.
                if on_error is not None:
                    _run_callback(on_error, exc, traceback.format_exc())
                else:
                    # No on_error handler -- without this the failure vanishes
                    # into the discarded Future with no trace anywhere
                    # (whole-branch diagnosis, MED).
                    _logger.exception(
                        "Job %s failed and no on_error callback was supplied.",
                        getattr(fn, "__name__", fn),
                    )
            else:
                _run_callback(on_result, value)
            finally:
                # Always, on both paths — the "job is over regardless of
                # outcome" hook every caller can rely on.
                _run_callback(on_finished)

        # The Future is intentionally discarded — see the module docstring.
        self._executor.submit(_wrapped)
        return SimpleJobHandle()

    def shutdown(self, *, wait: bool = True) -> None:
        """Stop the pool. **Not** part of :class:`JobRunner`.

        The application registers one of these as a process-lifetime
        singleton in ``bootstrap()`` and never calls this — the pool dies
        with the interpreter. It exists so tests (and any future caller
        that owns a runner with a bounded lifetime) can tear the executor
        down deterministically instead of leaking idle worker threads
        into a long-lived process.
        """
        self._executor.shutdown(wait=wait)
