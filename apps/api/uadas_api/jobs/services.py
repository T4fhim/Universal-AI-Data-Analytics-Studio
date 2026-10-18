# File: apps/api/uadas_api/jobs/services.py
"""Job lifecycle operations: create, cancel, claim, finish, sweep.

Why services (and not model methods or a Celery task body): every change to a job's state is a
**conditional update** -- ``UPDATE ... WHERE id = ? AND status IN (<legal sources>)`` -- so that
two workers, a worker and a sweeper, or a worker and a user cancelling can never both win, and
a redelivered message cannot move a finished job. This module is the only code that opens
:func:`~uadas_api.jobs.models.allow_status_write`. The same functions serve the web process
(create / cancel / get) and the worker (claim / finish) and the sweeper, so the rules live once.

Design rules, in the order a job meets them:

* **Authorized creation.** Only an active member holding ``write_data`` in the project's
  organization may create a job (:func:`require_capability`; the worker re-checks it, because a
  membership can be revoked between "queued" and "running").
* **Idempotent creation.** ``(organization, kind, idempotency_key)`` is unique. The same key with
  the same project and parameters returns the existing job (``created=False``) -- a retried
  upload request does not start a second ingest; the same key with *different* parameters is an
  :class:`IdempotencyConflictError`, never a silent reuse.
* **Enqueue after commit.** The message is sent from ``transaction.on_commit``: a worker must not
  be told about a row that is not yet visible, or that rolls back. If sending fails, the row stays
  ``queued`` with no ``enqueued_at`` and :func:`sweep_stale` sends it again.
* **Claim.** :func:`claim` moves ``queued -> running`` and counts the attempt; a *running* job is
  re-claimable only if its heartbeat is stale (the previous worker died), which makes a duplicate
  delivery harmless: the second delivery finds a fresh heartbeat and does nothing.
* **The sweeper** (:func:`sweep_stale`) is the safety net for everything the broker can lose: a
  stale ``running`` job is requeued (attempts left), failed as ``worker_lost`` (none left) or
  cancelled (a cancel was pending); a ``queued`` job whose message may be lost is sent again.
  It is idempotent -- run it as often as you like. Scheduling: ``celery beat`` runs the
  ``uadas.jobs.sweep`` task every minute (``CELERY_BEAT_SCHEDULE``), or run
  ``manage.py sweep_jobs`` from cron.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from uadas_api.accounts.models import Membership, Organization, User
from uadas_api.accounts.permissions import Capability, can
from uadas_api.jobs import queue as job_queue
from uadas_api.jobs.choices import JobStatus
from uadas_api.jobs.config import JobsConfig, get_config
from uadas_api.jobs.errors import (
    IdempotencyConflictError,
    JobErrorCode,
    JobPermissionError,
    message_for,
)
from uadas_api.jobs.models import (
    Job,
    allow_status_write,
    new_idempotency_key,
    validate_idempotency_key,
)
from uadas_api.jobs.registry import get_handler
from uadas_api.sandbox.runner import reap_workspaces
from uadas_api.tenancy import OrganizationRef
from uadas_api.workspaces.models import Project

_logger = logging.getLogger(__name__)

_SWEEP_BATCH = 500
_MAX_RESULT_BYTES = 16 * 1024


@dataclass(frozen=True)
class JobCreation:
    """The outcome of :func:`create_job`: the job and whether this call made it."""

    job: Job
    created: bool


class CancelOutcome(StrEnum):
    """What :func:`request_cancel` did."""

    CANCELLED = "cancelled"  # was queued: cancelled immediately
    REQUESTED = "requested"  # is running: the worker will stop at its next checkpoint
    ALREADY_FINISHED = "already_finished"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class SweepReport:
    """What one sweep did."""

    requeued: int = 0
    failed: int = 0
    cancelled: int = 0
    resent: int = 0
    send_failures: int = 0
    workspaces_reaped: int = 0


# ------------------------------------------------------------------ authorization


def require_capability(
    actor: User | None, organization_id: Any, capability: Capability
) -> Membership:
    """Return ``actor``'s membership if it is active and holds ``capability``; else raise.

    Raises :class:`JobPermissionError` for no actor, an inactive user, a non-member and a role
    below the capability: the caller maps it to a 403/404 as appropriate.
    """
    if not isinstance(actor, User) or not actor.is_active:
        raise JobPermissionError("no active user")
    membership = Membership.objects.filter(
        user=actor, organization_id=organization_id
    ).first()
    if membership is None or not can(membership.role, capability):
        raise JobPermissionError("not allowed")
    return membership


# ---------------------------------------------------------------------- creation


def _send(job_id: uuid.UUID, *, now: datetime) -> bool:
    """Hand ``job_id`` to the broker and stamp ``enqueued_at``; ``False`` if the broker is down."""
    try:
        job_queue.enqueue(job_id)
    except job_queue.QueueUnavailable:
        return False
    Job.objects.filter(pk=job_id, status=JobStatus.QUEUED).update(enqueued_at=now)
    return True


def _send_after_commit(job_id: uuid.UUID) -> None:
    _send(job_id, now=timezone.now())


def _same_request(existing: Job, project: Project, params: dict[str, Any]) -> bool:
    return existing.project_id == project.pk and existing.params == params


def create_job(
    *,
    project: Project,
    actor: User,
    kind: str,
    params: Mapping[str, Any],
    idempotency_key: str | None = None,
) -> JobCreation:
    """Create a queued job (or return the one this idempotency key already made) and enqueue it.

    Raises :class:`JobPermissionError` (not an active ``write_data`` member of the project's
    organization), Django's ``ValidationError`` (bad key, bad parameters),
    :class:`IdempotencyConflictError` (key reused for a different request) and ``KeyError`` for
    an unknown ``kind``. The broker is called from ``on_commit``, never from here.
    """
    require_capability(actor, project.organization_id, get_handler(kind).capability)
    key = idempotency_key if idempotency_key is not None else new_idempotency_key()
    validate_idempotency_key(
        key
    )  # ValidationError for a bad key, before any row exists
    handler = get_handler(kind)
    normalised = handler.validate_params(project.organization_id, params)
    scope = Job.objects.for_organization(project.organization_id)
    existing = scope.filter(kind=kind, idempotency_key=key).first()
    if existing is not None:
        if not _same_request(existing, project, normalised):
            raise IdempotencyConflictError
        return JobCreation(existing, created=False)
    try:
        with transaction.atomic():
            job = Job.objects.create(
                organization_id=project.organization_id,
                project=project,
                created_by=actor,
                kind=kind,
                params=normalised,
                idempotency_key=key,
            )
    except IntegrityError:
        # Lost a race with a concurrent request carrying the same key.
        existing = scope.filter(kind=kind, idempotency_key=key).first()
        if existing is None:
            raise
        if not _same_request(existing, project, normalised):
            raise IdempotencyConflictError from None
        return JobCreation(existing, created=False)
    transaction.on_commit(partial(_send_after_commit, job.pk), robust=True)
    return JobCreation(job, created=True)


def get_job(organization: OrganizationRef, job_id: uuid.UUID | str) -> Job | None:
    """The job with ``job_id`` if it belongs to ``organization``; else ``None`` (never another's)."""
    try:
        return Job.objects.for_organization(organization).filter(pk=job_id).first()
    except (ValidationError, ValueError):
        return None


# -------------------------------------------------------------------- cancellation


def request_cancel(
    *, organization: Organization, job_id: uuid.UUID | str, actor: User
) -> CancelOutcome:
    """Cancel a queued job now, or ask a running one to stop at its next checkpoint.

    A finished job is left exactly as it is. Raises :class:`JobPermissionError` unless ``actor``
    holds ``write_data`` in ``organization``; a job of another organization is ``NOT_FOUND``.
    """
    require_capability(actor, organization.pk, Capability.WRITE_DATA)
    job = get_job(organization, job_id)
    if job is None:
        return CancelOutcome.NOT_FOUND
    now = timezone.now()
    with allow_status_write():
        cancelled = Job.objects.filter(pk=job.pk, status=JobStatus.QUEUED).update(
            status=JobStatus.CANCELLED,
            finished_at=now,
            message="Cancelled",
            cancel_requested=True,
        )
    if cancelled:
        # A queued job's upload (and anything staged) belongs to nobody now: same cleanup as a
        # job that failed for good.
        run_abandon_hook(Job.objects.get(pk=job.pk))
        return CancelOutcome.CANCELLED
    flagged = Job.objects.filter(pk=job.pk, status=JobStatus.RUNNING).update(
        cancel_requested=True
    )
    if flagged:
        return CancelOutcome.REQUESTED
    return CancelOutcome.ALREADY_FINISHED


# --------------------------------------------------------- worker-side transitions


def claim(job_id: uuid.UUID | str, *, now: datetime, stale_after: int) -> Job | None:
    """Take a job to run: ``queued -> running``, or a dead worker's ``running`` job.

    Returns the claimed job (with ``attempts`` already incremented) or ``None`` if there is
    nothing to claim -- the job does not exist, is finished, or is running with a fresh
    heartbeat (another worker has it). The one place a job is looked up by id alone: the task
    message carries nothing else, so the organization is *read from the row*, and the caller
    (:mod:`uadas_api.jobs.execution`) re-checks ownership before any work.
    """
    with allow_status_write():
        claimed = Job.objects.filter(pk=job_id, status=JobStatus.QUEUED).update(
            status=JobStatus.RUNNING,
            attempts=F("attempts") + 1,
            started_at=now,
            heartbeat_at=now,
        )
    if not claimed:
        cutoff = now - timedelta(seconds=stale_after)
        claimed = (
            Job.objects.filter(pk=job_id, status=JobStatus.RUNNING)
            .filter(Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lt=cutoff))
            .update(attempts=F("attempts") + 1, heartbeat_at=now)
        )
    if not claimed:
        return None
    return Job.objects.filter(pk=job_id).first()


def _checked_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """A JSON-safe, size-bounded copy of ``result`` (ids, keys, counts: never rows of data)."""
    plain = dict(result)
    encoded = json.dumps(plain, sort_keys=True)  # TypeError for a non-JSON value
    if len(encoded) > _MAX_RESULT_BYTES:
        raise ValueError("a job result must be small: ids and counts, not data")
    return plain


def _running(job_id: uuid.UUID | str, attempt: int) -> QuerySet[Job]:
    """The row of ``job_id`` **if it is still running as attempt ``attempt``** (the fencing token).

    Every worker-side write goes through this. ``attempts`` is incremented by each claim, so when
    a heartbeat goes stale and another worker takes the job over, the first worker's token no
    longer matches: its late ``finish_*`` / ``requeue`` / progress writes find no row and report
    ``False`` instead of failing, requeueing, cancelling or committing the run that replaced it.
    """
    return Job.objects.filter(pk=job_id, status=JobStatus.RUNNING, attempts=attempt)


def finish_succeeded(
    job_id: uuid.UUID | str,
    *,
    attempt: int,
    result: Mapping[str, Any],
    now: datetime,
) -> bool:
    """``running -> succeeded`` with ``result``. ``False`` if this attempt no longer owns the job.

    Call it inside the transaction that commits whatever else the job produced, and raise if it
    returns ``False``: a job that lost its claim must not leave its side effects behind.
    """
    payload = _checked_result(result)
    with allow_status_write():
        updated = _running(job_id, attempt).update(
            status=JobStatus.SUCCEEDED,
            progress=100,
            message="Finished",
            result=payload,
            finished_at=now,
            heartbeat_at=now,
        )
    return updated == 1


def finish_failed(
    job_id: uuid.UUID | str,
    *,
    attempt: int,
    code: JobErrorCode,
    now: datetime,
) -> bool:
    """``running -> failed`` (this attempt only) with a closed code and its fixed sentence."""
    with allow_status_write():
        updated = _running(job_id, attempt).update(
            status=JobStatus.FAILED,
            error_code=code.value,
            error_message=message_for(code.value),
            message="Failed",
            finished_at=now,
        )
    return updated == 1


def finish_cancelled(job_id: uuid.UUID | str, *, attempt: int, now: datetime) -> bool:
    """``running -> cancelled`` (this attempt only)."""
    with allow_status_write():
        updated = _running(job_id, attempt).update(
            status=JobStatus.CANCELLED, message="Cancelled", finished_at=now
        )
    return updated == 1


def requeue_for_retry(
    job_id: uuid.UUID | str, *, attempt: int, delay: float, now: datetime
) -> bool:
    """``running -> queued`` after a retryable failure (this attempt only; the attempt stays counted).

    The retry's own message is already on its way (Celery's ``retry(countdown=...)``), so
    ``enqueued_at`` is *now*, and ``not_before`` says when it may run: the lost-message sweeper
    must not re-send a job that is merely backing off (which would defeat the backoff).
    """
    with allow_status_write():
        updated = _running(job_id, attempt).update(
            status=JobStatus.QUEUED,
            heartbeat_at=None,
            enqueued_at=now,
            not_before=now + timedelta(seconds=delay),
            message="Waiting to retry",
        )
    return updated == 1


def run_abandon_hook(job: Job) -> None:
    """Tell the job kind's handler that the job ended for good without succeeding (best effort).

    The one place that does it, so a job that fails in a worker, is cancelled while queued or is
    failed / cancelled by the sweeper (its worker was killed: the common way to lose staged
    objects) reaches the same cleanup. A failure in the hook is logged by class and never changes
    the job's outcome.
    """
    try:
        handler = get_handler(job.kind)
    except (KeyError, TypeError, ImportError):
        return
    if handler.on_abandon is None:
        return
    try:
        handler.on_abandon(job)
    except Exception as error:  # noqa: BLE001
        _logger.error("a job abandon step failed (%s)", type(error).__name__)


# ----------------------------------------------------------------------- sweeper


def _stale(cutoff: datetime) -> Q:
    return Q(heartbeat_at__isnull=True) | Q(heartbeat_at__lt=cutoff)


def _repair_stale(
    pk: uuid.UUID,
    attempts: int,
    cancel_requested: bool,
    max_attempts: int,
    stale_cutoff: datetime,
    moment: datetime,
) -> str:
    """Decide and apply the fate of one stale ``running`` job; ``""`` if it was not (still) stale.

    Cancelled if a cancel was pending, failed as ``worker_lost`` if no attempts are left, else
    back to ``queued``. The update re-checks staleness, so a worker that heartbeats between the
    sweeper's read and its write wins.
    """
    stale = Job.objects.filter(pk=pk, status=JobStatus.RUNNING).filter(
        _stale(stale_cutoff)
    )
    with allow_status_write():
        if cancel_requested:
            changed = stale.update(
                status=JobStatus.CANCELLED, message="Cancelled", finished_at=moment
            )
            return "cancelled" if changed else ""
        if attempts >= max_attempts:
            changed = stale.update(
                status=JobStatus.FAILED,
                error_code=JobErrorCode.WORKER_LOST.value,
                error_message=message_for(JobErrorCode.WORKER_LOST.value),
                message="Failed",
                finished_at=moment,
            )
            return "failed" if changed else ""
        changed = stale.update(
            status=JobStatus.QUEUED,
            heartbeat_at=None,
            enqueued_at=None,
            not_before=None,
            message="Waiting for a worker",
        )
        return "requeued" if changed else ""


def sweep_stale(
    *, now: datetime | None = None, config: JobsConfig | None = None
) -> SweepReport:
    """Repair what the broker and the workers can lose. Idempotent; safe to run concurrently.

    1. ``running`` jobs with a stale heartbeat (their worker died): cancelled if a cancel was
       pending, failed as ``worker_lost`` if no attempts are left, else back to ``queued`` and
       sent again. Each change is a conditional update that re-checks staleness, so a worker that
       wakes up mid-sweep and heartbeats wins.
    2. ``queued`` jobs whose message may be lost (never sent, or sent longer ago than
       ``requeue_after_seconds`` and still not claimed): sent again. A duplicate message is
       harmless -- the claim is atomic.
    """
    moment = now or timezone.now()
    cfg = config or get_config()
    stale_cutoff = moment - timedelta(seconds=cfg.stale_after_seconds)
    resend_cutoff = moment - timedelta(seconds=cfg.requeue_after_seconds)
    requeued = failed = cancelled = resent = send_failures = 0
    handled: set[uuid.UUID] = set()

    stale_rows = list(
        Job.objects.filter(status=JobStatus.RUNNING)
        .filter(_stale(stale_cutoff))
        .values_list("pk", "attempts", "cancel_requested")[:_SWEEP_BATCH]
    )
    for pk, attempts, cancel_requested in stale_rows:
        handled.add(pk)
        verdict = _repair_stale(
            pk, attempts, cancel_requested, cfg.max_attempts, stale_cutoff, moment
        )
        if verdict in {"cancelled", "failed"}:
            # The worker is gone (killed, OOM): what it staged in the bucket would be orphaned
            # forever. Same cleanup as a worker-side failure.
            run_abandon_hook(Job.objects.get(pk=pk))
            if verdict == "cancelled":
                cancelled += 1
            else:
                failed += 1
        elif verdict == "requeued":
            requeued += 1
            if not _send(pk, now=moment):
                send_failures += 1

    lost = list(
        Job.objects.filter(status=JobStatus.QUEUED)
        .filter(
            Q(enqueued_at__lt=resend_cutoff)
            | Q(enqueued_at__isnull=True, created_at__lt=resend_cutoff)
        )
        # A retry that is still backing off has its message in flight; do not defeat the delay.
        .filter(Q(not_before__isnull=True) | Q(not_before__lte=moment))
        .exclude(pk__in=handled)
        .values_list("pk", flat=True)[:_SWEEP_BATCH]
    )
    for pk in lost:
        if _send(pk, now=moment):
            resent += 1
        else:
            send_failures += 1

    # Directories of workers that were killed mid-job (they hold a tenant's file). Best effort.
    try:
        workspaces_reaped = reap_workspaces()
    except Exception as error:  # noqa: BLE001 - housekeeping must not fail the sweep
        _logger.error("the sandbox directory sweep failed (%s)", type(error).__name__)
        workspaces_reaped = 0

    report = SweepReport(
        requeued=requeued,
        failed=failed,
        cancelled=cancelled,
        resent=resent,
        send_failures=send_failures,
        workspaces_reaped=workspaces_reaped,
    )
    if any((requeued, failed, cancelled, resent, send_failures, workspaces_reaped)):
        _logger.info("job sweep: %s", report)
    return report
