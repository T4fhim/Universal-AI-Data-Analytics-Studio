# File: apps/api/uadas_api/jobs/execution.py
"""What a worker does with a job id. Celery-free, so every branch is testable without a broker.

:func:`execute_job` is the whole worker contract; ``tasks.run_job`` is a three-line shell around
it that turns an :class:`Outcome` into Celery's ack / retry. The steps, each of which a
redelivered, duplicated or poisoned message must survive:

1. **Claim** (:func:`uadas_api.jobs.services.claim`) -- an atomic conditional update. Nothing to
   claim (finished, or another worker holds it with a fresh heartbeat, or the id is unknown or
   malformed) is ``SKIPPED``: the message is acknowledged and nothing runs. This is what makes
   at-least-once delivery safe.
2. **Poison guard** -- ``attempts`` is incremented by every claim, so a message that keeps killing
   its worker (acks-late + reject-on-worker-lost redelivers it) is stopped here once it exceeds
   ``JOBS_MAX_ATTEMPTS``, whatever the broker thinks.
3. **Re-resolve and re-check ownership.** The message held only the job id. The organization,
   project and creator are loaded from the *row*; the creator must still be an active member
   holding the kind's capability *now* (a role can be revoked between queue and run). Failing
   that the job fails ``forbidden`` without the handler running.
4. **Run the handler**, which reports progress and checks for cancellation through its context.
5. **Commit atomically.** The handler's ``commit`` step (e.g. creating the ``DatasetRecord``) and
   the job's ``succeeded`` transition happen in one database transaction; if the job is no longer
   ours (cancelled, swept) the transaction rolls back and the handler's ``cleanup`` runs, so a job
   that does not succeed leaves no rows behind, and a job that succeeds leaves exactly one set.
6. **Classify failures** (:func:`uadas_api.jobs.errors.classify`) from the exception *type* only.
   Retryable ones (store or sandbox momentarily unavailable) go back to ``queued`` with an
   exponential backoff while attempts remain; everything else is final. The exception's text is
   never stored or logged: only its class and the traceback frames (source lines, no values).

Cancellation honours the flag at three points: before the handler starts, at every
``check_cancelled`` checkpoint inside it, and once more immediately before the commit.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from uadas_api.accounts.models import Organization
from uadas_api.jobs import services
from uadas_api.jobs.config import (
    JobsConfig,
    get_config,
    heartbeat_interval,
    retry_delay,
)
from uadas_api.jobs.errors import (
    Classified,
    JobCancelledError,
    JobError,
    JobErrorCode,
    JobLostError,
    JobPermissionError,
    classify,
)
from uadas_api.jobs.models import Job
from uadas_api.jobs.progress import ProgressSink
from uadas_api.jobs.registry import Completion, JobContext, JobHandler, get_handler
from uadas_api.workspaces.models import Project

_logger = logging.getLogger(__name__)


class OutcomeKind(StrEnum):
    """What the task shell should do with the message."""

    DONE = "done"  # the job reached a terminal state (success, failure or cancellation)
    SKIPPED = "skipped"  # nothing to do here: acknowledge and move on
    RETRY = "retry"  # put back in line; redeliver after ``delay`` seconds


@dataclass(frozen=True)
class Outcome:
    """The result of one :func:`execute_job` call."""

    kind: OutcomeKind
    delay: float = 0.0


def _log_failure(job_id: uuid.UUID, error: BaseException) -> None:
    """Record *that* a job failed and *where*, never *with what*.

    ``str(error)`` can hold a path, a fragment of the tenant's data or a connection string, and
    every tenant's jobs share one log. The class and the traceback frames (file, line, source)
    are enough to find the code.
    """
    frames = "".join(traceback.format_tb(error.__traceback__))
    _logger.error("job %s failed with %s\n%s", job_id, type(error).__name__, frames)


def _build_context(job: Job, handler: JobHandler, config: JobsConfig) -> JobContext:
    """Re-resolve everything from the row and re-check that the creator may still do this."""
    organization = Organization.objects.filter(pk=job.organization_id).first()
    project = (
        Project.objects.for_organization(job.organization_id)
        .filter(pk=job.project_id)
        .first()
    )
    if organization is None or project is None:
        raise JobError(JobErrorCode.NOT_FOUND)
    actor = job.created_by  # None if the user was deleted
    try:
        services.require_capability(actor, job.organization_id, handler.capability)
    except JobPermissionError:
        raise JobError(JobErrorCode.FORBIDDEN) from None
    sink = ProgressSink(
        job.pk,
        attempt=job.attempts,  # the fencing token: this worker's claim
        min_interval=config.progress_interval_ms / 1000,
    )
    return JobContext(
        job=job, organization=organization, project=project, actor=actor, sink=sink
    )


def _cleanup(completion: Completion | None) -> None:
    """Run a completion's cleanup, swallowing (and logging the class of) any failure of it."""
    if completion is None or completion.cleanup is None:
        return
    try:
        completion.cleanup()
    except Exception as error:  # noqa: BLE001
        _logger.error("a job cleanup step failed (%s)", type(error).__name__)


def _fail_for_good(
    job: Job, handler: JobHandler | None, code: JobErrorCode, now: datetime
) -> Outcome:
    # Fenced: a worker that was taken over finds no row to fail, and does nothing else either
    # (in particular it does not abandon the dataset the live run is still working on).
    if services.finish_failed(job.pk, attempt=job.attempts, code=code, now=now):
        if handler is not None:
            services.run_abandon_hook(job)
        return Outcome(OutcomeKind.DONE)
    return Outcome(OutcomeKind.SKIPPED)  # someone else owns or finished it


def _fail_or_retry(
    job: Job,
    handler: JobHandler | None,
    classified: Classified,
    config: JobsConfig,
    now: datetime,
) -> Outcome:
    if classified.retryable and job.attempts < config.max_attempts:
        delay = retry_delay(job.attempts, config)
        if services.requeue_for_retry(
            job.pk, attempt=job.attempts, delay=delay, now=now
        ):
            return Outcome(OutcomeKind.RETRY, delay)
        return Outcome(OutcomeKind.SKIPPED)
    return _fail_for_good(job, handler, classified.code, now)


def _commit(job: Job, completion: Completion, now: datetime) -> None:
    """Commit the handler's rows and the success state together, or neither."""
    with transaction.atomic():
        # A cancel requested while the handler worked wins up to this point.
        if Job.objects.filter(pk=job.pk, cancel_requested=True).exists():
            raise JobCancelledError
        if completion.commit is not None:
            completion.commit()
        if not services.finish_succeeded(
            job.pk, attempt=job.attempts, result=completion.result, now=now
        ):
            raise JobLostError


def execute_job(
    job_id: uuid.UUID | str, *, config: JobsConfig | None = None
) -> Outcome:
    """Run job ``job_id`` to a terminal state, or report that there is nothing to do or to retry."""
    cfg = config or get_config()
    try:
        job = services.claim(
            job_id, now=timezone.now(), stale_after=cfg.stale_after_seconds
        )
    except (ValidationError, ValueError):
        # Not a UUID: a garbage message. Acknowledge it; there is no job to touch.
        return Outcome(OutcomeKind.SKIPPED)
    if job is None:
        return Outcome(OutcomeKind.SKIPPED)

    try:
        handler: JobHandler | None = get_handler(job.kind)
    except (KeyError, TypeError, ImportError):
        handler = None
    if handler is None:
        return _fail_for_good(job, None, JobErrorCode.INTERNAL_ERROR, timezone.now())
    if job.attempts > cfg.max_attempts:
        return _fail_for_good(
            job, handler, JobErrorCode.TOO_MANY_ATTEMPTS, timezone.now()
        )
    if job.cancel_requested:
        if services.finish_cancelled(job.pk, attempt=job.attempts, now=timezone.now()):
            services.run_abandon_hook(job)
        return Outcome(OutcomeKind.DONE)

    completion: Completion | None = None
    try:
        context = _build_context(job, handler, cfg)
        # A thread keeps the heartbeat fresh while the handler is busy and silent (a download,
        # the sandboxed parse, an upload): without it a long valid run looks dead and is requeued.
        with context.sink.heartbeat(heartbeat_interval(cfg)):
            completion = handler.run(context)
        _commit(job, completion, timezone.now())
    except JobLostError:
        _cleanup(completion)
        return Outcome(OutcomeKind.SKIPPED)  # not ours any more; the new owner decides
    except JobCancelledError:
        _cleanup(completion)
        if services.finish_cancelled(job.pk, attempt=job.attempts, now=timezone.now()):
            services.run_abandon_hook(job)
        return Outcome(OutcomeKind.DONE)
    # Every failure becomes one closed code, whatever its type (classify never reads the text).
    except Exception as error:  # noqa: BLE001
        _cleanup(completion)
        _log_failure(job.pk, error)
        return _fail_or_retry(job, handler, classify(error), cfg, timezone.now())
    return Outcome(OutcomeKind.DONE)
