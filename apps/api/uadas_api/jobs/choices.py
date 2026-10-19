# File: apps/api/uadas_api/jobs/choices.py
"""The closed value sets of a job and the one definition of which state changes are legal.

Why here, and why a table: the state machine is the contract every writer (the worker, the
sweeper, a cancel request, the model's own ``save``) must honour, so it is defined once as data
and *enforced* in :mod:`uadas_api.jobs.models` and :mod:`uadas_api.jobs.services`; a hand-
rolled ``if status == ...`` in any caller would drift.

States and why each transition exists::

    queued    -> running     a worker claimed it
    queued    -> cancelled   cancelled before any worker started
    queued    -> failed      the sweeper gave up on a job whose message never produced a run
    running   -> queued      a retryable failure: back in line, attempt counted
    running   -> succeeded   the handler finished and its result committed
    running   -> failed      a terminal error (or the sweeper found the worker dead)
    running   -> cancelled   the handler honoured a cancellation request at a checkpoint

``succeeded``, ``failed`` and ``cancelled`` are **terminal and immutable**: nothing leaves them
and no field of such a row changes. ``JobKind`` is the closed set of things a job can be; every
member must have a handler (``tests/test_jobs_registry.py`` fails otherwise).
"""

from __future__ import annotations

from django.db import models


class JobKind(models.TextChoices):
    """What a job does. Grows with the pipeline (3.6: stage operations and report builds)."""

    INGEST_DATASET = "ingest_dataset", "Ingest dataset"
    # One catalog operation of one pipeline stage on one dataset (profile, clean, analyse,
    # forecast, chart): ``uadas_api.stages.run``.
    RUN_OPERATION = "run_operation", "Run a stage operation"
    # Render a Report row to its file in object storage: ``uadas_api.exports.service``.
    BUILD_REPORT = "build_report", "Build a report"


class JobStatus(models.TextChoices):
    """Where a job is in its life."""

    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


TERMINAL_STATUSES: frozenset[str] = frozenset(
    {JobStatus.SUCCEEDED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    JobStatus.QUEUED.value: frozenset(
        {JobStatus.RUNNING.value, JobStatus.CANCELLED.value, JobStatus.FAILED.value}
    ),
    JobStatus.RUNNING.value: frozenset(
        {
            JobStatus.QUEUED.value,
            JobStatus.SUCCEEDED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
    ),
    JobStatus.SUCCEEDED.value: frozenset(),
    JobStatus.FAILED.value: frozenset(),
    JobStatus.CANCELLED.value: frozenset(),
}


def can_transition(current: str, new: str) -> bool:
    """Whether a job may move from ``current`` to ``new`` (a no-op move is not a transition)."""
    return new in ALLOWED_TRANSITIONS.get(current, frozenset())


def sources_of(new: str) -> frozenset[str]:
    """Every status from which ``new`` may be reached (what a conditional update filters on)."""
    return frozenset(
        old for old, targets in ALLOWED_TRANSITIONS.items() if new in targets
    )
