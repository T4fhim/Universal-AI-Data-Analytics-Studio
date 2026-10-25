# File: apps/api/tests/test_web_report_attempts.py
"""A report build that lost its claim must never delete the file the live attempt committed.

Two attempts of one ``build_report`` job are interleaved by hand: attempt 1 builds and uploads its
file and then stalls (its heartbeat goes stale); attempt 2 takes the job over, builds *its* file and
commits the report READY; attempt 1 then tries to commit and is refused (fencing), and runs its
cleanup. The report must still point at attempt 2's file, which must still exist, while attempt 1's
own file is gone. Each attempt writes under its own key (``j<attempt>-<job>``, the scheme the stage
runs use), so a cleanup can only ever name its own object. The twin runs the same flow without the
takeover: one attempt, committed, nothing deleted.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from web_support import World, make_world

from uadas_api.exports.models import Report
from uadas_api.jobs import execution, services
from uadas_api.jobs.config import get_config
from uadas_api.jobs.errors import JobLostError
from uadas_api.jobs.models import Job
from uadas_api.jobs.registry import get_handler
from uadas_api.storage.store import get_store

pytestmark = pytest.mark.django_db


@pytest.fixture
def world() -> World:
    return make_world()


def _request(world: World) -> tuple[str, str]:
    accepted = world.api("editor").post(
        f"{world.base()}/reports",
        {"title": "Q", "format": "html", "dataset_id": str(world.dataset.pk)},
    )
    assert accepted.status_code == 202, accepted.content
    return accepted.json()["report"]["id"], accepted.json()["job_id"]


def _attempt(job_id: str) -> tuple[Job, Any, Any]:
    """Claim ``job_id`` as the next attempt and run the handler: (job, context, completion)."""
    cfg = get_config()
    job = services.claim(
        job_id, now=timezone.now(), stale_after=cfg.stale_after_seconds
    )
    assert job is not None
    handler = get_handler(job.kind)
    context = execution._build_context(job, handler, cfg)
    return job, context, handler.run(context)


def test_a_superseded_attempt_cannot_delete_the_live_attempts_file(
    world: World,
) -> None:
    report_id, job_id = _request(world)
    store = get_store(world.org)

    job1, _ctx1, completion1 = _attempt(
        job_id
    )  # attempt 1 builds and uploads, then stalls
    key1 = completion1.result["storage_key"]
    assert store.exists(key1) and "j001-" in key1
    Job.objects.filter(pk=job_id).update(
        heartbeat_at=timezone.now() - timedelta(hours=1)
    )

    job2, _ctx2, completion2 = _attempt(job_id)  # attempt 2 takes the job over
    key2 = completion2.result["storage_key"]
    assert job2.attempts == 2 and "j002-" in key2 and key1 != key2
    execution._commit(
        job2, completion2, timezone.now()
    )  # the live attempt commits READY

    with pytest.raises(JobLostError):  # attempt 1 is fenced out ...
        execution._commit(job1, completion1, timezone.now())
    assert completion1.cleanup is not None
    completion1.cleanup()  # ... and cleans up only what it made

    report = Report.objects.get(pk=report_id)
    assert report.status == "ready" and report.storage_key == key2
    assert store.exists(key2)  # the live attempt's file survived
    assert not store.exists(key1)  # the superseded attempt's own file is gone


def test_without_a_takeover_one_attempt_commits_and_nothing_is_deleted(
    world: World,
) -> None:
    report_id, job_id = _request(world)
    job, _ctx, completion = _attempt(job_id)
    execution._commit(job, completion, timezone.now())
    report = Report.objects.get(pk=report_id)
    assert (
        report.status == "ready"
        and report.storage_key == completion.result["storage_key"]
    )
    assert get_store(world.org).exists(report.storage_key)
