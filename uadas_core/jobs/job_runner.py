# File: uadas_core/jobs/job_runner.py
"""The :class:`JobRunner` protocol — "run this callable elsewhere, tell me how it went".

This is the seam the desktop→web transition turns on. Today the only
implementation is
:class:`~uadas_core.jobs.thread_pool_executor_job_runner.ThreadPoolExecutorJobRunner`
(a local ``ThreadPoolExecutor``); Phase 3 is expected to add a
``DjangoTasksJobRunner`` that hands ``fn`` to a separate worker *process*
and receives its outcome over an HTTP webhook. Both fit the same shape
*only because the contract is callback-based*:

* A ``Future`` cannot cross a process boundary, so there is nothing to
  hand back that works for both an in-process thread and an out-of-process
  task queue. Callbacks do: a local runner simply calls them; a remote
  runner invokes them from whatever context receives the webhook.
* :class:`JobHandle` stays deliberately opaque for the same reason — in
  1.2 it is a small dataclass carrying a bookkeeping uuid; in Phase 3 it
  would be a task id the caller can poll or cancel. Callers keep the
  handle alive for the job's duration and otherwise treat it as a token,
  never introspecting it.

**Thread affinity is not this protocol's problem.** Callbacks fire from
the runner's own execution context (a pool thread, an HTTP handler,
whatever). A consumer that needs them marshalled onto a specific thread —
e.g. :class:`~src.workers.base_worker.BaseWorker`, which must re-emit them
as Qt signals on the UI thread — is responsible for that itself. This
keeps :mod:`uadas_core.jobs` free of any GUI event-loop assumption.

See ``plans/phase-1-2-jobrunner-design.md`` for the design write-up and
:mod:`uadas_core.jobs` for how the pieces relate.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

# T links a job's return type to its ``on_result`` callback: a runner
# handed ``fn: Callable[..., T]`` promises ``on_result`` (if given) is
# called with a ``T``. Declared module-level so both appear in the one
# ``run`` signature below; this makes ``run`` generic in ``T`` rather than
# the protocol class itself, which is what we want (each call resolves its
# own ``T`` from the ``fn`` passed).
T = TypeVar("T")


class JobHandle(Protocol):
    """Opaque token a caller holds for the lifetime of a submitted job.

    Intentionally featureless: the caller's only contract is to keep a
    reference to it until the job's terminal callback has fired, and never
    to depend on its concrete type or attributes.

    * Phase 1.2:
      :class:`~uadas_core.jobs.thread_pool_executor_job_runner.SimpleJobHandle`,
      a frozen dataclass wrapping a uuid used only for logging/bookkeeping.
    * Phase 3: expected to become a task id that a ``DjangoTasksJobRunner``
      can use to query status or request cancellation.

    Keeping it opaque now is what lets that change land without touching
    any call site — see this module's docstring.
    """


class JobRunner(Protocol):
    """Runs a callable away from the calling thread and reports the outcome via callbacks.

    Implementations: the in-process
    :class:`~uadas_core.jobs.thread_pool_executor_job_runner.ThreadPoolExecutorJobRunner`
    (1.2), a future out-of-process ``DjangoTasksJobRunner`` (Phase 3).

    :meth:`run` is the whole protocol. There is deliberately no
    ``cancel`` / ``result`` / ``wait`` — :class:`~src.workers.base_worker.BaseWorker`,
    the only 1.2 consumer, has no cancellation today, and adding surface
    area the transition does not yet need would be speculative (see the
    scope fence in ``plans/phase-1-2-jobrunner-design.md``). The protocol
    is designed so those can be added later without breaking this
    signature.
    """

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
    ) -> JobHandle:
        """Schedule ``fn(*args, **kwargs)`` to run off the calling thread.

        Contract every implementation must honour:

        * ``fn`` runs in the runner's execution context, never on the
          calling thread.
        * If ``report_progress`` is ``True``, a
          ``progress_callback: Callable[[int, str], None]`` is injected
          into ``kwargs`` before ``fn`` is called — exactly as
          :class:`~src.workers.base_worker.BaseWorker` does today
          (``base_worker.py``: the ``report_progress`` branch of
          ``__init__``). It forwards to ``on_progress`` when that was
          supplied, and is a no-op otherwise, so ``fn`` can always call
          ``progress_callback(pct, msg)`` unconditionally.
        * Exactly one of ``on_result`` / ``on_error`` fires per job:
          ``on_result`` with ``fn``'s return value on success,
          ``on_error(exc, traceback_str)`` if ``fn`` raised (the
          traceback is pre-formatted to a ``str`` because a traceback
          object is not safe to carry across a thread/process boundary
          the way its string rendering is).
        * ``on_finished`` fires exactly once afterwards, on both paths —
          the callback for "the job is over, regardless of outcome".
        * Callbacks fire from the runner's context, not the caller's; a
          consumer needing thread affinity handles that itself.

        Args:
            fn: The callable to execute. Must not touch thread-affine
                objects (Qt widgets, etc.) directly — its result flows
                back through the callbacks.
            *args: Positional arguments forwarded to ``fn``.
            report_progress: Inject a ``progress_callback`` kwarg into
                ``fn``'s call (see above).
            on_result: Called once with ``fn``'s return value on success.
            on_error: Called once with ``(exception, traceback_str)`` if
                ``fn`` raised.
            on_finished: Called once after ``on_result`` / ``on_error``,
                on every outcome.
            on_progress: Called with ``(percent, message)`` each time
                ``fn`` invokes the injected ``progress_callback`` (only
                meaningful with ``report_progress=True``).
            **kwargs: Keyword arguments forwarded to ``fn``.

        Returns:
            A :class:`JobHandle` the caller keeps referenced until the
            job's terminal callback has fired.
        """
        ...
