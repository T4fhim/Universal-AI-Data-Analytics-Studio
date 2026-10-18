# File: apps/api/uadas_api/jobs/queue.py
"""The queue facade: the one function the rest of the code calls to hand a job to a worker.

Why a facade: call sites (services, the sweeper, later the API routers) must not know there is
a Celery. They say "this job id is ready" (:func:`enqueue`) and get either success or
:class:`QueueUnavailable`. Swapping the courier (to a ``django.tasks`` backend, to RQ) then
touches this module, :mod:`~uadas_api.jobs.celery_app` and :mod:`~uadas_api.jobs.tasks` -- and
nothing else. ``tests/test_jobs_boundary.py`` fails if any other module imports ``celery`` or
``kombu``.

Relationship to Django's ``django.tasks`` (6.1): its API (``@task``, ``enqueue``, ``TASKS``
backends) is the intended future shape, but 6.1 ships only an in-process ``ImmediateBackend``
and a ``DummyBackend``; a durable queue needs a third-party backend, and none of them provides
what the contract below needs -- bounded retries with backoff, late acknowledgement,
visibility-timeout and time-limit control, a periodic sweeper -- so the courier is Celery behind
this facade. See ``plans/phase-3-5-jobs.md``.

What :func:`enqueue` promises: it sends one message whose body is just the job's id (a string),
JSON-serialized. The message is a *hint*, not the job: if it is lost, duplicated or delivered
late, the database row and the conditional claim in :func:`uadas_api.jobs.services.claim` keep
the job correct; if it cannot be sent, the row stays ``queued`` and the sweeper sends it again.
"""

from __future__ import annotations

import logging
import uuid

_logger = logging.getLogger(__name__)


class QueueUnavailable(Exception):
    """The broker could not be reached. The job row is unaffected and will be re-sent."""


def enqueue(job_id: uuid.UUID) -> None:
    """Hand ``job_id`` to a worker. Raises :class:`QueueUnavailable` if the broker is down.

    In eager mode (tests, ``JOBS_EAGER``) this runs the job inline before returning.
    """
    # Imported here: the module must be importable (by services, by tests, by `check`) with no
    # broker and without loading Celery's machinery.
    from kombu.exceptions import KombuError

    from uadas_api.jobs.tasks import run_job

    try:
        run_job.apply_async(args=[str(job_id)])
    except (OSError, KombuError) as error:
        # The class only: a broker error can carry the broker URL, password included.
        _logger.warning("could not enqueue a job (%s)", type(error).__name__)
        raise QueueUnavailable(type(error).__name__) from None
