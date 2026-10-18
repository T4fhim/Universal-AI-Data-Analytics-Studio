# File: apps/api/tests/test_jobs_integration.py
"""A real Redis, a real ``celery worker`` process, PostgreSQL and MinIO, end to end.

What the hermetic suite cannot show, this does: that the *task message* (an id, JSON) is
delivered through a real broker to a *separate process* that re-resolves everything from the
database, runs the sandbox child against a file fetched from real object storage, and commits
the dataset and the job's success together; that a malformed file fails safe **without taking
down the worker**, which then processes the next job; and that a duplicate delivery of a
finished job's message changes nothing.

Opt-in like the MinIO tests (``JOBS_INTEGRATION=1`` plus the services' variables, see
``jobs_support.py``); ``test_jobs_ci_guard.py`` makes CI fail if it would silently skip. The
test process creates data (committed, so ``transaction=True``) in the *test database* and hands
that database's URL, the broker and a private queue name to the worker, so nothing here can
touch a developer's real data or consume another run's messages.

Not covered here, on purpose: a worker killed mid-job (the broker redelivers only after the
visibility timeout, which is deliberately long) -- that path is covered by the claim / sweeper /
attempt-limit tests, which model the same states directly.
"""

from __future__ import annotations

import io
import os
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import connection
from factories import make_organization, make_user
from jobs_support import (
    Worker,
    database_url,
    integration_enabled,
    running_worker,
)
from storage_support import minio_backend

from uadas_api.accounts.models import Membership, Role
from uadas_api.ingest import service
from uadas_api.jobs import queue as job_queue
from uadas_api.jobs.celery_app import app
from uadas_api.jobs.models import Job
from uadas_api.storage import keys
from uadas_api.storage.store import get_store, override_backend
from uadas_api.workspaces.models import DatasetRecord, Project

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skipif(
        not integration_enabled(),
        reason="set JOBS_INTEGRATION=1, CELERY_BROKER_URL/REDIS_URL, a postgres DATABASE_URL "
        "and the STORAGE_* variables to run against the real services",
    ),
]

CSV = b"name,qty\nwidget,3\ngadget,5\n"


def _broker() -> str:
    return os.environ.get("CELERY_BROKER_URL") or os.environ["REDIS_URL"]


@pytest.fixture
def queue_name() -> Iterator[str]:
    name = f"uadas-it-{uuid.uuid4().hex[:8]}"
    yield name
    import redis

    redis.Redis.from_url(_broker()).delete(name)  # nothing of this run outlives it


@pytest.fixture
def real_store() -> Iterator[None]:
    """The test process talks to the same MinIO bucket as the worker (not the in-memory fake)."""
    with override_backend(minio_backend()):
        yield


@pytest.fixture
def broker_app(queue_name: str) -> Iterator[None]:
    """Point the live Celery app at the real broker and this run's queue (it is eager in tests)."""
    # The app reads Django's `CELERY_*` settings with a namespace, and a lookup tries the
    # *prefixed* key first: an override under the plain name (`task_always_eager`) is shadowed by
    # the settings' `CELERY_TASK_ALWAYS_EAGER = True` and silently does nothing. Override under
    # the prefixed names, and undo by removing them from the app's changes layer.
    overrides = {
        "CELERY_TASK_ALWAYS_EAGER": False,
        "CELERY_BROKER_URL": _broker(),
        "CELERY_TASK_DEFAULT_QUEUE": queue_name,
    }
    app.conf.update(**overrides)
    # Pools cache the broker they were built for (and a *closed* pool cannot be reused), so each
    # test starts from fresh ones built against the real broker configured just above.
    app._pool = None
    app.amqp._producer_pool = None
    # If this were still eager the test process would run the jobs itself and the worker would
    # prove nothing, so make that impossible to miss.
    assert app.conf.task_always_eager is False
    assert app.conf.task_default_queue == queue_name
    try:
        yield
    finally:
        for name in overrides:
            app.conf.changes.pop(name, None)
        app._pool = None
        app.amqp._producer_pool = None


def _worker_env(queue: str) -> dict[str, str]:
    base = {k: os.environ[k] for k in ("PATH",) if k in os.environ}
    if os.name == "nt":
        base["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    storage = {
        k: os.environ[k]
        for k in (
            "STORAGE_ENDPOINT_URL",
            "STORAGE_BUCKET",
            "STORAGE_ACCESS_KEY_ID",
            "STORAGE_SECRET_ACCESS_KEY",
            "STORAGE_ADDRESSING",
        )
        if k in os.environ
    }
    return {
        **base,
        **storage,
        # `dev` settings: not eager, not the in-memory store, and every value explicit below.
        "DJANGO_SETTINGS_MODULE": "uadas_api.settings.dev",
        "DATABASE_URL": database_url(connection.settings_dict),
        "CELERY_BROKER_URL": _broker(),
        "JOBS_QUEUE": queue,
        "JOBS_PROGRESS_INTERVAL_MS": "0",
        "PYTHONUNBUFFERED": "1",
    }


@pytest.fixture
def worker(queue_name: str, real_store: None, broker_app: None) -> Iterator[Worker]:
    with running_worker(_worker_env(queue_name), queue_name) as running:
        yield running


class Tenant:
    def __init__(self) -> None:
        self.org = make_organization()
        self.user = make_user()
        Membership.objects.create(
            user=self.user, organization=self.org, role=Role.EDITOR
        )
        self.project = Project.objects.create(organization=self.org, name="p")
        self.store = get_store(self.org.pk)

    def request(self, data: bytes, filename: str) -> tuple[Job, dict[str, Any]]:
        dataset_id = uuid.uuid4()
        key = keys.dataset_original_key(self.org.pk, dataset_id)
        self.store.put(
            key,
            data,
            content_type="application/octet-stream",
            allowed_content_types=["application/octet-stream"],
            original_filename=filename,
        )
        job = service.request_ingest(
            project=self.project,
            actor=self.user,
            dataset_id=dataset_id,
            original_key=key,
            filename=filename,
            content_type="application/octet-stream",
        ).job
        return job, {"dataset_id": dataset_id, "key": key}


def wait_for(job: Job, worker: Worker, *, timeout: float = 180.0) -> Job:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job.refresh_from_db()
        if job.status in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.5)
    raise AssertionError(
        f"job still {job.status} after {timeout}s; worker output:\n{worker.output()}"
    )


@pytest.fixture
def tenant(real_store: None) -> Tenant:
    return Tenant()


def test_a_job_created_in_one_process_is_run_by_a_worker_in_another(
    tenant: Tenant, worker: Worker
) -> None:
    job, ids = tenant.request(CSV, "sales.csv")
    finished = wait_for(job, worker)
    assert (finished.status, finished.attempts, finished.error_code) == (
        "succeeded",
        1,
        "",
    )
    (record,) = DatasetRecord.objects.for_organization(tenant.org)
    assert record.pk == ids["dataset_id"] and (
        record.row_count,
        record.column_count,
    ) == (2, 2)
    import pandas as pd  # type: ignore[import-untyped]

    frame = pd.read_parquet(io.BytesIO(tenant.store.get(record.storage_key)))
    assert frame["name"].tolist() == ["widget", "gadget"]
    assert worker.wait_for_count(" succeeded in ", 1) >= 1, worker.output(80)


def test_a_malformed_file_fails_safe_and_the_worker_goes_on_to_the_next_job(
    tenant: Tenant, worker: Worker
) -> None:
    bad, bad_ids = tenant.request(
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Typ",
        "broken.pdf",
    )
    failed = wait_for(bad, worker)
    assert (failed.status, failed.error_code) == ("failed", "parse_error")
    assert (
        not DatasetRecord.objects.for_organization(tenant.org)
        .filter(pk=bad_ids["dataset_id"])
        .exists()
    )
    # The worker process survived the hostile file and processes the next job normally.
    good, _ = tenant.request(CSV, "sales.csv")
    assert wait_for(good, worker).status == "succeeded"


def test_a_duplicate_delivery_of_a_finished_jobs_message_changes_nothing(
    tenant: Tenant, worker: Worker
) -> None:
    job, _ = tenant.request(CSV, "sales.csv")
    assert wait_for(job, worker).status == "succeeded"
    # Celery logs one such line per finished task, slightly after the job's own commit.
    before = worker.wait_for_count(" succeeded in ", 1)
    job_queue.enqueue(job.pk)  # the broker "redelivers" the same message
    job_queue.enqueue(job.pk)
    deadline = time.monotonic() + 60
    while worker.count(" succeeded in ") < before + 2 and time.monotonic() < deadline:
        time.sleep(0.5)
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("succeeded", 1)
    assert DatasetRecord.objects.for_organization(tenant.org).count() == 1
