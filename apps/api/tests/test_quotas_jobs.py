# File: apps/api/tests/test_quotas_jobs.py
"""Job time against the monthly quota: refused when used up, billed once per attempt, never by a loser.

Why: the job services are where compute is spent, so they are where it is metered. The properties
that matter, each with its positive twin: a new job is refused once the month's job time is gone
(while a replay of an existing job, and any job with room, still goes through); the time of an
attempt is billed when the attempt *ends and wins the fence* -- so a worker that was superseded
cannot bill, and an attempt that ends twice bills once -- and a retry bills its own run, not the
earlier one again.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from factories import make_organization, make_user

from uadas_api.accounts.models import Membership, Role
from uadas_api.jobs import services
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.errors import JobErrorCode
from uadas_api.jobs.registry import JobHandler, override_handler
from uadas_api.quotas import service as quotas
from uadas_api.quotas.choices import UsageKind
from uadas_api.quotas.errors import QuotaExceededError
from uadas_api.quotas.models import UsageLedger
from uadas_api.workspaces.models import Project

pytestmark = pytest.mark.django_db

KIND = JobKind.INGEST_DATASET.value
SECONDS = UsageKind.JOB_SECONDS.value


@pytest.fixture(autouse=True)
def _permissive_handler(monkeypatch: pytest.MonkeyPatch) -> Any:
    from uadas_api.jobs import queue as job_queue

    monkeypatch.setattr(job_queue, "enqueue", lambda job_id: None)
    handler = JobHandler(validate_params=lambda org, params: dict(params), run=lambda ctx: None)  # type: ignore[arg-type,return-value]
    with override_handler(KIND, handler):
        yield


@pytest.fixture
def editor() -> tuple[Any, Any, Project]:
    org, user = make_organization(), make_user()
    Membership.objects.create(user=user, organization=org, role=Role.EDITOR)
    project = Project.objects.create(organization=org, name=f"p-{uuid.uuid4().hex[:6]}")
    return org, user, project


def create(project: Project, user: Any, **kw: Any) -> services.JobCreation:
    return services.create_job(
        project=project, actor=user, kind=KIND, params=kw.pop("params", {"a": 1}), **kw
    )


def used(org: Any) -> int:
    return quotas.usage_for(org, SECONDS)


def limit(settings: Any, seconds: int | None) -> None:
    settings.UADAS_QUOTA = {**settings.UADAS_QUOTA, "max_job_seconds": seconds}


def running(project: Project, user: Any, started: Any) -> Any:
    job = create(project, user).job
    claimed = services.claim(job.pk, now=started, stale_after=120)
    assert claimed is not None
    return claimed


# ----------------------------------------------------------------- creation is refused


def test_a_job_is_refused_once_the_months_job_time_is_used_up(
    editor: Any, settings: Any
) -> None:
    org, user, project = editor
    limit(settings, 100)
    quotas.charge(org, SECONDS, 100, "earlier")
    with pytest.raises(QuotaExceededError) as raised:
        create(project, user)
    assert raised.value.kind == SECONDS
    assert services.Job.objects.count() == 0


def test_a_job_is_accepted_while_there_is_room(editor: Any, settings: Any) -> None:
    org, user, project = editor
    limit(settings, 100)
    quotas.charge(org, SECONDS, 99, "earlier")  # one second left is room
    assert create(project, user).created is True


def test_a_replay_of_an_existing_job_is_not_refused_when_the_quota_is_gone(
    editor: Any, settings: Any
) -> None:
    org, user, project = editor
    limit(settings, 100)
    first = create(project, user, idempotency_key="same")
    quotas.charge(org, SECONDS, 500, "burst")  # now over the limit
    again = create(project, user, idempotency_key="same")
    assert (again.created, again.job.pk) == (False, first.job.pk)
    with pytest.raises(QuotaExceededError):  # while a *new* job is refused (the twin)
        create(project, user, idempotency_key="different")


def test_another_organizations_usage_does_not_refuse_my_job(
    editor: Any, settings: Any
) -> None:
    _, user, project = editor
    limit(settings, 100)
    quotas.charge(make_organization(), SECONDS, 10**6, "someone-else")
    assert create(project, user).created is True


# ------------------------------------------------------------------------ billing


def test_a_finished_attempt_is_billed_by_its_wall_clock_time(editor: Any) -> None:
    org, user, project = editor
    start = timezone.now()
    job = running(project, user, start)
    assert services.finish_succeeded(
        job.pk, attempt=1, result={}, now=start + timedelta(seconds=90, milliseconds=1)
    )
    assert used(org) == 91  # rounded up
    entry = UsageLedger.objects.for_organization(org).get(kind=SECONDS)
    assert entry.source_key == f"job:{job.pk}:1" and entry.amount == 91


def test_a_failed_and_a_cancelled_attempt_are_billed_too(editor: Any) -> None:
    org, user, project = editor
    start = timezone.now()
    failed = running(project, user, start)
    services.finish_failed(
        failed.pk,
        attempt=1,
        code=JobErrorCode.PARSE_ERROR,
        now=start + timedelta(seconds=10),
    )
    cancelled = running(project, user, start)
    services.finish_cancelled(cancelled.pk, attempt=1, now=start + timedelta(seconds=5))
    assert used(org) == 15


def test_an_instant_job_still_costs_a_second(editor: Any) -> None:
    org, user, project = editor
    start = timezone.now()
    job = running(project, user, start)
    services.finish_succeeded(job.pk, attempt=1, result={}, now=start)
    assert used(org) == 1


def test_an_attempt_that_ends_twice_is_billed_once(editor: Any) -> None:
    org, user, project = editor
    start = timezone.now()
    job = running(project, user, start)
    end = start + timedelta(seconds=30)
    assert services.finish_succeeded(job.pk, attempt=1, result={}, now=end) is True
    # A redelivered or racing second finish finds the job finished: no row, no charge.
    assert services.finish_succeeded(job.pk, attempt=1, result={}, now=end) is False
    assert (
        services.finish_failed(
            job.pk, attempt=1, code=JobErrorCode.INTERNAL_ERROR, now=end
        )
        is False
    )
    assert used(org) == 30


def test_a_superseded_worker_cannot_bill(editor: Any) -> None:
    org, user, project = editor
    start = timezone.now()
    job = running(project, user, start)  # attempt 1
    later = start + timedelta(seconds=500)
    taken = services.claim(
        job.pk, now=later, stale_after=120
    )  # a new worker: attempt 2
    assert taken is not None and taken.attempts == 2
    # The first worker wakes up and tries to finish with its old fencing token ...
    assert services.finish_succeeded(job.pk, attempt=1, result={}, now=later) is False
    assert used(org) == 0  # ... and bills nothing
    # The live attempt then finishes and is billed (the positive twin).
    assert services.finish_succeeded(
        job.pk, attempt=2, result={}, now=later + timedelta(seconds=7)
    )
    assert used(org) == 507  # from the job's first start, once
    assert (
        not UsageLedger.objects.for_organization(org)
        .filter(source_key=f"job:{job.pk}:1")
        .exists()
    )


def test_each_attempt_of_a_retried_job_bills_its_own_run_once(editor: Any) -> None:
    org, user, project = editor
    start = timezone.now()
    job = running(project, user, start)
    assert services.requeue_for_retry(
        job.pk, attempt=1, delay=1.0, now=start + timedelta(seconds=20)
    )
    assert used(org) == 20  # the first attempt, billed as it ended
    # The same requeue again is not an attempt that owns the job: nothing more.
    assert not services.requeue_for_retry(
        job.pk, attempt=1, delay=1.0, now=start + timedelta(seconds=25)
    )
    assert used(org) == 20
    second_start = start + timedelta(seconds=40)
    again = services.claim(job.pk, now=second_start, stale_after=120)
    assert again is not None and again.attempts == 2
    services.finish_succeeded(
        job.pk, attempt=2, result={}, now=second_start + timedelta(seconds=15)
    )
    assert used(org) == 35  # 20 + 15, each attempt exactly once
    keys = set(
        UsageLedger.objects.for_organization(org).values_list("source_key", flat=True)
    )
    assert keys == {f"job:{job.pk}:1", f"job:{job.pk}:2"}


def test_billing_goes_to_the_jobs_own_organization(editor: Any) -> None:
    org, user, project = editor
    other = make_organization()
    start = timezone.now()
    job = running(project, user, start)
    services.finish_succeeded(
        job.pk, attempt=1, result={}, now=start + timedelta(seconds=3)
    )
    assert (used(org), used(other)) == (3, 0)


def test_a_billing_failure_never_changes_the_jobs_outcome(
    editor: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, user, project = editor
    start = timezone.now()
    job = running(project, user, start)

    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("ledger down")

    monkeypatch.setattr(quotas, "charge", broken)
    assert services.finish_succeeded(job.pk, attempt=1, result={}, now=start) is True
    job.refresh_from_db()
    assert job.status == "succeeded"
