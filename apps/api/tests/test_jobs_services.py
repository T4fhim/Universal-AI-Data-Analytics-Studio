# File: apps/api/tests/test_jobs_services.py
"""Creating, cancelling and sweeping jobs; the progress sink.

Why: the services are where the job contract is *kept* -- authorized creation, idempotency,
"enqueue only after the row is committed", conditional transitions, throttled progress that
doubles as a heartbeat, and a sweeper for workers that died. The broker is replaced by a
recorder (``queue.enqueue``); the worker path is in ``test_jobs_execution.py``.

Refusals are paired with the accepted twin: an editor may create a job and a viewer may not; a
second request with the same key and the same parameters returns the first job and one with
different parameters is a conflict; a fresh heartbeat protects a job from the sweeper and a
stale one does not.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from factories import make_organization, make_user

from uadas_api.accounts.models import Membership, Role
from uadas_api.jobs import queue as job_queue
from uadas_api.jobs import services
from uadas_api.jobs.choices import JobKind
from uadas_api.jobs.config import JobsConfig, get_config
from uadas_api.jobs.errors import (
    IdempotencyConflictError,
    JobCancelledError,
    JobErrorCode,
    JobLostError,
    JobPermissionError,
)
from uadas_api.jobs.models import Job, allow_status_write
from uadas_api.jobs.progress import ProgressSink, clean_message
from uadas_api.jobs.registry import JobHandler, override_handler
from uadas_api.workspaces.models import Project

pytestmark = pytest.mark.django_db

KIND = JobKind.INGEST_DATASET.value
OnCommit = Callable[..., Any]


class Sent(list[uuid.UUID]):
    """Records every job id handed to the broker."""


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[Sent]:
    recorder = Sent()
    monkeypatch.setattr(job_queue, "enqueue", lambda job_id: recorder.append(job_id))
    yield recorder


@pytest.fixture(autouse=True)
def _permissive_handler() -> Iterator[None]:
    """A handler that accepts any params, so these tests do not depend on a real kind."""
    handler = JobHandler(validate_params=lambda org, params: dict(params), run=lambda ctx: None)  # type: ignore[arg-type,return-value]
    with override_handler(KIND, handler):
        yield


def member(role: Role) -> tuple[Any, Any, Project]:
    org = make_organization()
    user = make_user()
    Membership.objects.create(user=user, organization=org, role=role)
    project = Project.objects.create(organization=org, name=f"p-{uuid.uuid4().hex[:6]}")
    return org, user, project


def create(project: Project, user: Any, **kw: Any) -> services.JobCreation:
    return services.create_job(
        project=project, actor=user, kind=KIND, params=kw.pop("params", {"a": 1}), **kw
    )


# --------------------------------------------------------------------- creation


def test_an_editor_creates_a_queued_job_in_the_projects_organization() -> None:
    org, user, project = member(Role.EDITOR)
    created = create(project, user)
    job = created.job
    assert created.created is True
    assert (job.organization_id, job.project_id, job.created_by_id) == (
        org.pk,
        project.pk,
        user.pk,
    )
    assert (job.status, job.attempts, job.progress) == ("queued", 0, 0)
    assert job.idempotency_key  # one is generated when the caller gives none


@pytest.mark.parametrize("role", [Role.EDITOR, Role.ADMIN, Role.OWNER])
def test_editors_and_above_may_create(role: Role) -> None:
    _, user, project = member(role)
    assert create(project, user).created


def test_a_viewer_and_a_non_member_may_not_create() -> None:
    _, viewer, project = member(Role.VIEWER)
    with pytest.raises(JobPermissionError):
        create(project, viewer)
    with pytest.raises(JobPermissionError):
        create(project, make_user())
    assert Job.objects.count() == 0


def test_an_inactive_user_may_not_create() -> None:
    _, user, project = member(Role.EDITOR)
    user.is_active = False
    user.save()
    with pytest.raises(JobPermissionError):
        create(project, user)


def test_the_same_key_and_params_return_the_same_job_without_a_second_row() -> None:
    _, user, project = member(Role.EDITOR)
    first = create(project, user, idempotency_key="upload-42")
    again = create(project, user, idempotency_key="upload-42")
    assert (first.created, again.created) == (True, False)
    assert again.job.pk == first.job.pk
    assert Job.objects.count() == 1


def test_the_same_key_with_different_params_is_a_conflict() -> None:
    _, user, project = member(Role.EDITOR)
    create(project, user, idempotency_key="upload-42", params={"a": 1})
    with pytest.raises(IdempotencyConflictError):
        create(project, user, idempotency_key="upload-42", params={"a": 2})
    assert Job.objects.count() == 1


def test_the_same_key_in_another_organization_is_a_different_job() -> None:
    _, user_a, project_a = member(Role.EDITOR)
    _, user_b, project_b = member(Role.EDITOR)
    first = create(project_a, user_a, idempotency_key="k")
    second = create(project_b, user_b, idempotency_key="k")
    assert first.job.pk != second.job.pk


def test_an_invalid_key_is_refused_before_any_row_exists() -> None:
    from django.core.exceptions import ValidationError

    _, user, project = member(Role.EDITOR)
    for bad in ("has space", "x" * 65, "semi;colon"):
        with pytest.raises(ValidationError):
            create(project, user, idempotency_key=bad)
    assert Job.objects.count() == 0


def test_params_are_validated_by_the_kinds_handler() -> None:
    from django.core.exceptions import ValidationError

    def strict(organization_id: Any, params: Any) -> dict[str, Any]:
        if "dataset_id" not in params:
            raise ValidationError("dataset_id is required")
        return {"dataset_id": str(params["dataset_id"])}

    _, user, project = member(Role.EDITOR)
    with override_handler(KIND, JobHandler(validate_params=strict, run=lambda ctx: None)):  # type: ignore[arg-type,return-value]
        with pytest.raises(ValidationError):
            create(project, user, params={})
        job = create(project, user, params={"dataset_id": 7}).job
    assert job.params == {"dataset_id": "7"}  # stored in the validated, normalised form


def test_a_project_of_another_organization_is_refused_for_a_member_elsewhere() -> None:
    _, user, _own = member(Role.EDITOR)
    _, _other_user, foreign_project = member(Role.EDITOR)
    with pytest.raises(JobPermissionError):
        create(foreign_project, user)


# ------------------------------------------------------ enqueue after the commit


def test_the_job_is_enqueued_only_after_its_transaction_commits(
    sent: Sent, django_capture_on_commit_callbacks: OnCommit
) -> None:
    _, user, project = member(Role.EDITOR)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        job = create(project, user).job
    assert sent == []  # not sent while the transaction is open
    assert len(callbacks) == 1
    callbacks[0]()
    assert sent == [job.pk]
    job.refresh_from_db()
    assert job.enqueued_at is not None


def test_a_duplicate_request_does_not_enqueue_a_second_message(
    sent: Sent, django_capture_on_commit_callbacks: OnCommit
) -> None:
    _, user, project = member(Role.EDITOR)
    with django_capture_on_commit_callbacks(execute=True):
        create(project, user, idempotency_key="once")
        create(project, user, idempotency_key="once")
    assert len(sent) == 1


def test_a_broker_outage_after_commit_leaves_the_job_queued_for_the_sweeper(
    monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: OnCommit
) -> None:
    def broken(job_id: uuid.UUID) -> None:
        raise job_queue.QueueUnavailable("redis is down")

    monkeypatch.setattr(job_queue, "enqueue", broken)
    _, user, project = member(Role.EDITOR)
    with django_capture_on_commit_callbacks(execute=True):
        job = create(project, user).job
    job.refresh_from_db()
    assert (job.status, job.enqueued_at) == (
        "queued",
        None,
    )  # nothing lost: the row exists


# ------------------------------------------------------------------ cancellation


def make_running(project: Project, user: Any, **kw: Any) -> Job:
    job = create(project, user, **kw).job
    claimed = services.claim(job.pk, now=timezone.now(), stale_after=120)
    assert claimed is not None
    return claimed


def test_cancelling_a_queued_job_cancels_it_at_once() -> None:
    org, user, project = member(Role.EDITOR)
    job = create(project, user).job
    outcome = services.request_cancel(organization=org, job_id=job.pk, actor=user)
    assert outcome is services.CancelOutcome.CANCELLED
    job.refresh_from_db()
    assert (job.status, job.finished_at is not None) == ("cancelled", True)


def test_cancelling_a_running_job_only_raises_the_flag() -> None:
    org, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    outcome = services.request_cancel(organization=org, job_id=job.pk, actor=user)
    assert outcome is services.CancelOutcome.REQUESTED
    job.refresh_from_db()
    assert (job.status, job.cancel_requested) == ("running", True)


def test_cancelling_a_finished_job_changes_nothing() -> None:
    org, user, project = member(Role.EDITOR)
    job = create(project, user).job
    services.request_cancel(organization=org, job_id=job.pk, actor=user)
    again = services.request_cancel(organization=org, job_id=job.pk, actor=user)
    assert again is services.CancelOutcome.ALREADY_FINISHED
    job.refresh_from_db()
    assert job.status == "cancelled"


def test_cancel_is_tenant_scoped_and_role_checked() -> None:
    org, user, project = member(Role.EDITOR)
    job = create(project, user).job
    other_org, other_user, _ = member(Role.EDITOR)
    assert (
        services.request_cancel(organization=other_org, job_id=job.pk, actor=other_user)
        is services.CancelOutcome.NOT_FOUND
    )
    viewer = make_user()
    Membership.objects.create(user=viewer, organization=org, role=Role.VIEWER)
    with pytest.raises(JobPermissionError):
        services.request_cancel(organization=org, job_id=job.pk, actor=viewer)
    job.refresh_from_db()
    assert (job.status, job.cancel_requested) == ("queued", False)


def test_get_job_is_tenant_scoped() -> None:
    org, user, project = member(Role.EDITOR)
    job = create(project, user).job
    assert services.get_job(org, job.pk) == job
    assert services.get_job(make_organization(), job.pk) is None


# ------------------------------------------------------------------------- claims


def test_claim_moves_queued_to_running_and_counts_the_attempt() -> None:
    _, user, project = member(Role.EDITOR)
    job = create(project, user).job
    now = timezone.now()
    claimed = services.claim(job.pk, now=now, stale_after=120)
    assert claimed is not None
    assert (claimed.status, claimed.attempts) == ("running", 1)
    assert claimed.started_at == now and claimed.heartbeat_at == now


def test_a_running_job_with_a_fresh_heartbeat_cannot_be_claimed_again() -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    assert services.claim(job.pk, now=timezone.now(), stale_after=120) is None
    job.refresh_from_db()
    assert job.attempts == 1


def test_a_running_job_with_a_stale_heartbeat_is_taken_over() -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    later = timezone.now() + timedelta(seconds=500)
    taken = services.claim(job.pk, now=later, stale_after=120)
    assert taken is not None
    assert (taken.status, taken.attempts) == ("running", 2)


@pytest.mark.parametrize("terminal", ["cancelled", "failed", "succeeded"])
def test_a_finished_job_cannot_be_claimed(terminal: str) -> None:
    _, user, project = member(Role.EDITOR)
    job = create(project, user).job
    with allow_status_write():
        fields: dict[str, Any] = {"status": terminal, "finished_at": timezone.now()}
        if terminal == "failed":
            fields["error_code"] = "parse_error"
        Job.objects.filter(pk=job.pk).update(**fields)
    assert (
        services.claim(job.pk, now=timezone.now() + timedelta(days=1), stale_after=1)
        is None
    )


def test_claiming_a_missing_job_is_none() -> None:
    assert services.claim(uuid.uuid4(), now=timezone.now(), stale_after=120) is None


# --------------------------------------------------------------- progress sink


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_progress_is_written_throttled_and_doubles_as_a_heartbeat() -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    clock = Clock()
    sink = ProgressSink(job.pk, attempt=job.attempts, min_interval=1.0, clock=clock)
    with CaptureQueriesContext(connection) as queries:
        for percent in range(0, 50):
            sink(percent, "Working")  # fifty calls in the same instant
    writes = [q for q in queries.captured_queries if q["sql"].startswith("UPDATE")]
    assert len(writes) == 1  # the first call; the rest were throttled
    clock.now += 1.5
    sink(60, "Still working")
    job.refresh_from_db()
    assert (job.progress, job.message) == (60, "Still working")
    assert job.heartbeat_at is not None


def test_a_forced_report_ignores_the_throttle() -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    sink = ProgressSink(job.pk, attempt=job.attempts, min_interval=60.0, clock=Clock())
    sink(10, "one")
    sink.report(20, "two", force=True)
    job.refresh_from_db()
    assert (job.progress, job.message) == (20, "two")


def test_progress_is_clamped_to_the_valid_range() -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    sink = ProgressSink(job.pk, attempt=job.attempts, min_interval=0, clock=Clock())
    sink(150, "over")
    job.refresh_from_db()
    assert job.progress == 100
    sink(-20, "under")
    job.refresh_from_db()
    assert job.progress == 0


def test_messages_are_cleaned_and_bounded() -> None:
    assert (
        clean_message("line one\nline two\x1b[31m red\x00")
        == "line one line two [31m red"
    )
    assert len(clean_message("x" * 500)) == 200
    assert clean_message("plain") == "plain"  # the positive twin
    assert clean_message("   ") == ""


def test_the_sink_refuses_a_job_that_is_no_longer_running() -> None:
    org, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    sink = ProgressSink(job.pk, attempt=job.attempts, min_interval=0, clock=Clock())
    sink(10, "fine")
    with allow_status_write():
        Job.objects.filter(pk=job.pk).update(
            status="failed",
            finished_at=timezone.now(),
            error_code=JobErrorCode.WORKER_LOST.value,
        )
    with pytest.raises(JobLostError):
        sink(20, "too late")
    job.refresh_from_db()
    assert job.progress == 10  # the terminal row was not touched


def test_check_cancelled_raises_once_a_cancel_was_requested() -> None:
    org, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    sink = ProgressSink(job.pk, attempt=job.attempts, min_interval=0, clock=Clock())
    sink.check_cancelled()  # nothing requested: returns quietly
    services.request_cancel(organization=org, job_id=job.pk, actor=user)
    with pytest.raises(JobCancelledError):
        sink.check_cancelled()


def test_the_sink_accepts_the_cores_progress_callback_shape() -> None:
    # uadas_core.jobs injects `progress_callback: Callable[[int, str], None]`; the sink must be
    # usable wherever that shape is (without importing uadas_core.jobs).
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    callback: Callable[[int, str], None] = ProgressSink(
        job.pk, attempt=job.attempts, min_interval=0, clock=Clock()
    )
    callback(42, "from the core")
    job.refresh_from_db()
    assert job.progress == 42


# ------------------------------------------------------------------- the sweeper


def config(**kw: Any) -> JobsConfig:
    from dataclasses import replace

    return replace(get_config(), **kw)


def age_heartbeat(job: Job, seconds: int) -> None:
    Job.objects.filter(pk=job.pk).update(
        heartbeat_at=timezone.now() - timedelta(seconds=seconds)
    )


def test_a_job_with_a_fresh_heartbeat_is_left_alone(sent: Sent) -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    report = services.sweep_stale(config=config(stale_after_seconds=120))
    assert (report.requeued, report.failed) == (0, 0)
    job.refresh_from_db()
    assert job.status == "running"
    assert sent == []


def test_a_stale_running_job_with_attempts_left_goes_back_to_the_queue(
    sent: Sent,
) -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    age_heartbeat(job, 500)
    report = services.sweep_stale(
        config=config(stale_after_seconds=120, max_attempts=3)
    )
    assert (report.requeued, report.failed) == (1, 0)
    job.refresh_from_db()
    assert (job.status, job.attempts) == ("queued", 1)
    assert sent == [job.pk]


def test_a_stale_running_job_out_of_attempts_is_failed_as_worker_lost(
    sent: Sent,
) -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    Job.objects.filter(pk=job.pk).update(attempts=3)
    age_heartbeat(job, 500)
    report = services.sweep_stale(
        config=config(stale_after_seconds=120, max_attempts=3)
    )
    assert (report.requeued, report.failed) == (0, 1)
    job.refresh_from_db()
    assert (job.status, job.error_code) == ("failed", JobErrorCode.WORKER_LOST.value)
    assert job.error_message and job.finished_at is not None
    assert sent == []


def test_a_stale_running_job_with_a_cancel_request_is_cancelled(sent: Sent) -> None:
    org, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    services.request_cancel(organization=org, job_id=job.pk, actor=user)
    age_heartbeat(job, 500)
    report = services.sweep_stale(config=config(stale_after_seconds=120))
    assert report.cancelled == 1
    job.refresh_from_db()
    assert job.status == "cancelled"
    assert sent == []


def test_a_queued_job_whose_message_may_be_lost_is_sent_again(sent: Sent) -> None:
    _, user, project = member(Role.EDITOR)
    never_sent = create(
        project, user
    ).job  # enqueued_at is None: the broker call failed
    old = create(project, user).job
    Job.objects.filter(pk=old.pk).update(
        enqueued_at=timezone.now() - timedelta(seconds=1000)
    )
    recent = create(project, user).job
    Job.objects.filter(pk=recent.pk).update(enqueued_at=timezone.now())
    # age the never-sent one past the grace so a brand-new row is not raced
    Job.objects.filter(pk=never_sent.pk).update(
        created_at=timezone.now() - timedelta(seconds=1000)
    )
    report = services.sweep_stale(config=config(requeue_after_seconds=300))
    assert report.resent == 2
    assert set(sent) == {never_sent.pk, old.pk}  # not `recent`


def test_a_brand_new_unsent_job_is_not_resent_inside_the_grace_period(
    sent: Sent,
) -> None:
    _, user, project = member(Role.EDITOR)
    create(project, user)  # created just now, enqueue callback not yet run
    services.sweep_stale(config=config(requeue_after_seconds=300))
    assert sent == []


def test_sweeping_twice_is_harmless(sent: Sent) -> None:
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    age_heartbeat(job, 500)
    cfg = config(stale_after_seconds=120, max_attempts=3)
    services.sweep_stale(config=cfg)
    second = services.sweep_stale(config=cfg)
    assert (second.requeued, second.failed) == (0, 0)
    assert sent == [job.pk]  # one resend, from the first sweep


def test_the_sweeper_survives_a_broker_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(job_id: uuid.UUID) -> None:
        raise job_queue.QueueUnavailable("down")

    monkeypatch.setattr(job_queue, "enqueue", broken)
    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    age_heartbeat(job, 500)
    report = services.sweep_stale(
        config=config(stale_after_seconds=120, max_attempts=3)
    )
    assert report.send_failures == 1
    job.refresh_from_db()
    assert job.status == "queued"  # the state change stands; the next sweep re-sends


def test_the_sweep_command_runs_and_reports(
    sent: Sent, capsys: pytest.CaptureFixture[str]
) -> None:
    from django.core.management import call_command

    _, user, project = member(Role.EDITOR)
    job = make_running(project, user)
    age_heartbeat(job, 5000)
    call_command("sweep_jobs")
    out = capsys.readouterr().out
    assert "requeued=1" in out
    assert sent == [job.pk]
