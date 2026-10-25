# File: apps/api/uadas_api/jobs/progress.py
"""The progress sink: a worker's way to tell the world how far it got, across processes.

Why this exists: ``uadas_core.jobs`` and Celery both report progress through an *in-process*
callback (``progress_callback(percent, message)``), and a worker is a different process from
the web server that wants to show a progress bar (and from 3.7's SSE stream). The bridge is the
:class:`~uadas_api.jobs.models.Job` row: :class:`ProgressSink` is a callable with the core's
callback shape that writes ``progress`` / ``message`` / ``heartbeat_at`` there. It deliberately
does not import ``uadas_core.jobs`` (``.importlinter``): it only has to be *call-compatible*
with that shape (:data:`ProgressCallback`).

Three jobs in one:

* **Progress** -- throttled so a tight loop calling it a million times costs one ``UPDATE`` per
  interval (and the first call always writes, so a job shows life at once).
* **Heartbeat** -- every write refreshes ``heartbeat_at``; the stale-job sweeper reads that to
  tell a slow job from a dead worker. A handler that is busy but silent calls
  :meth:`ProgressSink.report` at its checkpoints -- and, because the longest silent steps (a download,
  the sandboxed parse, an upload) cannot checkpoint, a :class:`Heartbeat` thread refreshes it for
  the whole run (``execution.execute_job`` starts one around every handler).
* **Cancellation and loss detection** -- :meth:`check_cancelled` is the checkpoint a handler
  calls between steps: it raises :class:`~uadas_api.jobs.errors.JobCancelledError` if a cancel
  was requested and :class:`~uadas_api.jobs.errors.JobLostError` if the row is no longer
  ``running`` (the sweeper gave up on it, or another worker took it over). A write to a job
  that is no longer running also raises ``JobLostError``: a worker that lost its job must stop,
  not keep going and overwrite its successor.

**Nothing about the user's data may be passed as a message.** Handlers pass fixed strings
(``"Parsing file"``); :func:`clean_message` strips control characters (so no terminal escape or
newline injection) and caps the length as a backstop, not as permission to forward text.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections.abc import Callable

from django.db import DatabaseError, connections
from django.db.models import QuerySet
from django.utils import timezone

from uadas_api.jobs.choices import JobStatus
from uadas_api.jobs.errors import JobCancelledError, JobLostError
from uadas_api.jobs.models import Job

# The shape `uadas_core.jobs` injects as `progress_callback`.
ProgressCallback = Callable[[int, str], None]

_logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 200
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")


def clean_message(text: str) -> str:
    """One printable line, at most :data:`MAX_MESSAGE_CHARS` characters."""
    flattened = _CONTROL.sub(" ", str(text))
    return " ".join(flattened.split())[:MAX_MESSAGE_CHARS]


class Heartbeat:
    """Keeps a running job's ``heartbeat_at`` fresh from a thread, for the whole run.

    Why a thread: the handler is *silent* for the longest steps (a 100 MB download, the sandbox
    parse of up to ``SANDBOX_WALL_SECONDS``, a 512 MB upload) -- no progress call, no heartbeat --
    and a heartbeat older than ``JOBS_STALE_AFTER_SECONDS`` makes the sweeper requeue a perfectly
    healthy job, which then runs twice. The beat is fenced like every worker write
    (``attempts`` must still be this worker's): when it fails the job has been taken over, and
    :attr:`lost` is set so the handler's next checkpoint stops instead of racing its successor.

    The thread has its own database connection (Django connections are thread-local) and closes it
    on exit. A transient database error is logged by class and retried at the next beat; only a
    *missing* row (nothing updated) means "lost".
    """

    THREAD_NAME = "uadas-job-heartbeat"

    def __init__(self, job_id: uuid.UUID, *, attempt: int, interval: float) -> None:
        self._job_id = job_id
        self._attempt = attempt
        self._interval = interval
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def beat(self) -> bool:
        """Refresh the heartbeat once. ``False`` (and :attr:`lost` set) if the job is not ours."""
        updated = Job.objects.filter(
            pk=self._job_id, status=JobStatus.RUNNING, attempts=self._attempt
        ).update(heartbeat_at=timezone.now())
        if updated != 1:
            self.lost.set()
            return False
        return True

    def _run(self) -> None:
        try:
            while not self._stop.wait(self._interval):
                try:
                    if not self.beat():
                        return
                except DatabaseError as error:
                    # Class only; the next beat tries again (the window is minutes, a beat is seconds).
                    _logger.warning("a job heartbeat failed (%s)", type(error).__name__)
        finally:
            connections.close_all()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name=self.THREAD_NAME, daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=10)

    def __enter__(self) -> Heartbeat:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


class ProgressSink:
    """Writes one job's progress to its row. Construct with the job id; call like a callback.

    ``attempt`` is the worker's fencing token (the job's ``attempts`` as of its claim): every write
    is conditional on it, so a worker that has been superseded raises
    :class:`~uadas_api.jobs.errors.JobLostError` instead of overwriting the run that replaced it.
    """

    def __init__(
        self,
        job_id: uuid.UUID,
        *,
        attempt: int,
        min_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._job_id = job_id
        self._attempt = attempt
        self._min_interval = min_interval
        self._clock = clock
        self._last_write: float | None = None
        self._lost = threading.Event()

    def __call__(self, percent: int, message: str = "") -> None:
        self.report(percent, message)

    def _mine(self) -> QuerySet[Job]:
        return Job.objects.filter(
            pk=self._job_id, status=JobStatus.RUNNING, attempts=self._attempt
        )

    def report(self, percent: int, message: str = "", *, force: bool = False) -> None:
        """Record progress (and a heartbeat), unless throttled. ``force`` ignores the throttle."""
        if self._lost.is_set():
            raise JobLostError
        now = self._clock()
        if (
            not force
            and self._last_write is not None
            and now - self._last_write < self._min_interval
        ):
            return
        updated = self._mine().update(
            progress=max(0, min(100, int(percent))),
            message=clean_message(message),
            heartbeat_at=timezone.now(),
        )
        if updated != 1:
            raise JobLostError
        self._last_write = now

    def heartbeat(self, interval: float) -> Heartbeat:
        """A :class:`Heartbeat` for this job and attempt (use it as a context manager).

        It shares this sink's loss flag, so a failed beat makes the next :meth:`report` or
        :meth:`check_cancelled` raise ``JobLostError``.
        """
        beat = Heartbeat(self._job_id, attempt=self._attempt, interval=interval)
        beat.lost = self._lost
        return beat

    def check_cancelled(self) -> None:
        """The checkpoint between steps: raise if cancelled or if this job is no longer ours."""
        if self._lost.is_set():
            raise JobLostError
        state = (
            Job.objects.filter(pk=self._job_id)
            .values_list("status", "cancel_requested", "attempts")
            .first()
        )
        if state is None or state[0] != JobStatus.RUNNING or state[2] != self._attempt:
            raise JobLostError
        if state[1]:
            raise JobCancelledError
