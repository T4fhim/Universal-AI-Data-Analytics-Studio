# File: apps/api/uadas_api/jobs/tasks.py
"""The Celery tasks: thin shells around :mod:`uadas_api.jobs.execution` and the sweeper.

Why so little here: every decision lives in Celery-free code that tests can drive directly. A
task body does three things -- pass the id on, translate an
:class:`~uadas_api.jobs.execution.Outcome` into Celery's vocabulary (acknowledge, or retry after
a delay), and nothing else. The message carries **only a job id string** (JSON): no organization,
no project, no parameters -- a worker re-derives all of it from the database row and re-checks
that the creator may still do this (``execution._build_context``).

Delivery semantics (``settings/_jobs.py``): at-least-once. ``acks_late`` + ``reject_on_worker_lost``
mean a message is acknowledged after the task returns and redelivered if the worker dies, so a
task may run more than once for one job; ``execute_job``'s atomic claim makes that harmless.
``max_retries=None`` on purpose: retries are bounded by the database's attempt counter
(``JOBS_MAX_ATTEMPTS``), which also covers redeliveries Celery does not count as retries.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from celery import Task
from celery.signals import worker_process_init, worker_ready

from uadas_api.jobs.celery_app import app
from uadas_api.jobs.execution import OutcomeKind, execute_job
from uadas_api.jobs.services import sweep_stale
from uadas_api.sandbox.isolation import harden_worker
from uadas_api.sandbox.runner import reap_workspaces

_logger = logging.getLogger(__name__)

RUN_TASK_NAME = "uadas.jobs.run"
SWEEP_TASK_NAME = "uadas.jobs.sweep"


@app.task(
    bind=True,
    name=RUN_TASK_NAME,
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=None,
    ignore_result=True,
)
def run_job(self: Task, job_id: str) -> None:
    """Run one job by id. A retryable failure re-sends the message after the backoff."""
    outcome = execute_job(job_id)
    if outcome.kind is OutcomeKind.RETRY:
        raise self.retry(countdown=outcome.delay)


@worker_process_init.connect
@worker_ready.connect
def _on_worker_start(**kwargs: Any) -> None:
    """When a worker (or one of its pool processes) starts: harden it and sweep dead workers' dirs.

    ``worker_ready`` covers the solo pool (no pool processes exist), ``worker_process_init`` each
    prefork child. Making the process non-dumpable is what keeps a same-uid parser child from
    reading its environment out of ``/proc``; sweeping removes job directories a SIGKILLed worker
    left holding a tenant's file. Neither may stop a worker from starting.
    """
    harden_worker()
    try:
        reap_workspaces()
    except Exception as error:  # noqa: BLE001
        _logger.error(
            "the sandbox directory sweep failed at start (%s)", type(error).__name__
        )


@app.task(name=SWEEP_TASK_NAME, ignore_result=True)
def sweep() -> dict[str, Any]:
    """Run the stale-job sweeper once (``celery beat`` schedules this every minute)."""
    return asdict(sweep_stale())
